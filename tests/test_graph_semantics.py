"""What the graph features mean, and what they must never claim.

Two false positives found by audit and fixed here, both of which BLOCKED a
payment:

  A new shop whose four customers also use a large delivery app. Four shared
  payers out of four, ratio 1.0, so the overlap rule fired - against a peer
  with a hundred and twenty payers, every one of them a repeat customer.
  fraud_graph.detect_rings never had this bug: it requires BOTH payees to be
  in its one-shot `eligible` set, and the read path had dropped that half.

  A household of five paying two new local shops. Both payees young, both
  one-shot, complete overlap. detect_rings names this exact false positive in
  its docstring and claims the one-shot gate prevents it - which it does not
  on cold start, because a payee three days old has not failed to retain
  customers, nobody has had time to return.

The second is a pre-existing weakness in a dashboard heuristic. It became
serious when the heuristic moved onto the path that stops payments, and that
is the general lesson these tests hold: the evidential bar for blocking is
higher than the bar for a list a human skims.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import backend.app.services.profile_store as store


def iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


@pytest.fixture()
def db(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(store, "DB_PATH", tmp / "sem.db")
    monkeypatch.setattr(store, "DATA_DIR", tmp)
    store._SCHEMA_DONE.clear()
    from backend.app.services.payee_reputation import connect

    conn = connect()
    yield conn
    conn.close()
    store._SCHEMA_DONE.clear()


def pay(conn, payee, payer, amount=500.0, days_ago=1.0):
    from backend.app.services.payee_reputation import record_payment

    record_payment(payee, payer_id=payer, amount=amount, at=iso(days_ago), conn=conn)


def view(conn, payee):
    from backend.app.services.graph_cache import graph_view

    return graph_view(conn, payee)


def graph_row(conn, payee, amount=2000.0):
    from backend.app.services.payee_check import check_payee

    result = check_payee(payee, payer_id="a_stranger", amount=amount, conn=conn)
    return next(e for e in result["evidence"] if e["family"] == "graph"), result


# ── A-E. Overlap semantics ───────────────────────────────────────────────────

def test_a_new_payee_with_one_payer_carries_no_graph_evidence(db):
    pay(db, "brandnew@ybl", "alice")
    v = view(db, "brandnew@ybl")
    assert v.available is True
    assert v.payer_count == 1
    assert v.shared_payer_peak is None and v.overlap_ratio is None
    row, _ = graph_row(db, "brandnew@ybl")
    assert row["score"] == 0 and row["facts"] == []


def test_two_payees_sharing_one_payer_is_not_evidence(db):
    """One person paying two shops proves nothing at all."""
    pay(db, "shopA@ybl", "alice")
    pay(db, "shopB@ybl", "alice")
    v = view(db, "shopA@ybl")
    assert v.shared_payer_peak is None, "below the shared-payer floor"
    assert v.position_findings == []


def test_sharing_customers_with_a_popular_merchant_is_not_evidence(db):
    """The regression that blocked a new shop.

    Its four customers also used a large delivery app. Four shared out of
    four, ratio 1.0 - and the peer had 120 payers, every one a repeat. Sharing
    customers with a popular merchant is what being a shop in the same street
    looks like.

    Before: graph score 70, fact graph_position, verdict BLOCK.
    After:  graph score 0, no fact, verdict APPROVE.
    """
    for i in range(400):
        pay(db, "bigapp@ibl", f"cust{i % 120}", days_ago=300 - i * 0.5)
    for i in range(4):
        pay(db, "newshop@ybl", f"cust{i}", days_ago=2)

    peer = view(db, "bigapp@ibl")
    assert peer.repeat_ratio == 1.0, "the peer keeps its customers"

    v = view(db, "newshop@ybl")
    assert v.shared_payer_peak == 4, "the overlap is observed and reported"
    assert v.overlap_ratio is None, "but it carries no evidential weight"
    assert v.position_findings == []

    row, result = graph_row(db, "newshop@ybl")
    assert row["score"] == 0 and row["facts"] == []
    assert result["verdict"] == "APPROVE"


def test_a_household_paying_two_new_local_shops_is_not_a_ring(db):
    """Five people, two shops, complete overlap, both a few days old.

    Both young payees show a zero repeat ratio, and on cold start that is not
    a finding - nobody has had time to come back. The one-shot reading needs
    enough payers on both sides to be a measurement.

    Before: graph score 70, fact graph_position, verdict BLOCK.
    After:  graph score 0, no fact.
    """
    for i in range(5):
        pay(db, "grocer@ybl", f"fam{i}", days_ago=3)
        pay(db, "chemist@ybl", f"fam{i}", days_ago=3)

    v = view(db, "grocer@ybl")
    assert v.shared_payer_peak == 5
    assert v.overlap_ratio is None
    assert v.position_findings == []
    row, _ = graph_row(db, "grocer@ybl")
    assert row["score"] == 0 and "graph_position" not in row["facts"]


def test_identical_payer_sets_at_scale_do_fire(db):
    """Twelve one-shot payers, both addresses, complete overlap. This is the
    shape the feature exists to catch, and it must survive the guards added
    for the cases above."""
    for i in range(12):
        pay(db, "ca@fastpay", f"m{i}", amount=4500, days_ago=2)
        pay(db, "cb@fastpay", f"m{i}", amount=4500, days_ago=2)

    v = view(db, "ca@fastpay")
    assert v.shared_payer_peak == 12 and v.overlap_ratio == 1.0
    assert v.position_findings

    row, result = graph_row(db, "ca@fastpay", amount=4500.0)
    assert row["facts"] == ["graph_position"]
    assert row["score"] > 0
    assert result["verdict"] == "BLOCK"


def test_disjoint_payer_sets_produce_no_overlap(db):
    for i in range(12):
        pay(db, "x@ybl", f"xa{i}", days_ago=2)
        pay(db, "y@ybl", f"yb{i}", days_ago=2)
    v = view(db, "x@ybl")
    assert v.shared_payer_peak is None and v.position_findings == []


# ── F-G. Maintenance semantics ───────────────────────────────────────────────

def test_a_repeat_payment_moves_the_ratio_and_can_clear_the_overlap(db):
    """Customers coming back is the thing that distinguishes a merchant."""
    for i in range(12):
        pay(db, "pa@ybl", f"m{i}", days_ago=20)
        pay(db, "pb@ybl", f"m{i}", days_ago=20)
    assert view(db, "pa@ybl").position_findings, "one-shot on both sides"

    for i in range(12):                       # everyone returns to pb
        pay(db, "pb@ybl", f"m{i}", days_ago=1)
    assert view(db, "pb@ybl").repeat_ratio == 1.0
    assert view(db, "pa@ybl").position_findings == [], "peer now keeps its customers"


def test_a_new_edge_grows_the_component_without_a_rebuild(db):
    pay(db, "s1@ybl", "alice")
    pay(db, "s2@ybl", "bob")
    assert view(db, "s1@ybl").component_size == 2
    pay(db, "s2@ybl", "alice")
    assert view(db, "s1@ybl").component_size == 4


def test_component_size_alone_is_never_a_finding(db):
    """Every address in a connected payment network sits in one large
    component. Treating connectedness as suspicious flags the whole graph."""
    for i in range(60):
        pay(db, "hub@ibl", f"c{i}", days_ago=200 - i)
    for i in range(30):
        pay(db, "ordinary@ybl", f"c{i}", days_ago=100 - i)
        pay(db, "ordinary@ybl", f"c{i}", days_ago=50 - i)

    v = view(db, "ordinary@ybl")
    assert v.component_size > 50, "deeply connected"
    assert v.position_findings == [], "and that is not evidence of anything"


# ── H. Temporal ──────────────────────────────────────────────────────────────

def test_the_arrival_window_ignores_payments_that_are_not_first_sightings(db):
    """arrival_span is first-seen to first-seen. Using the last payment let a
    single returning payer stretch the window and silence a burst."""
    for i in range(12):
        pay(db, "burst@fastpay", f"p{i}", days_ago=1 - i * 0.05)
    before = view(db, "burst@fastpay")
    assert any("arrived within" in f for f in before.shape_findings)

    pay(db, "burst@fastpay", "p0", days_ago=0)
    after = view(db, "burst@fastpay")
    assert after.arrival_span_days == pytest.approx(before.arrival_span_days, abs=0.01)
    assert any("arrived within" in f for f in after.shape_findings)


def test_no_feature_can_see_a_payment_that_has_not_been_observed(db):
    for i in range(11):
        pay(db, "shop@ybl", f"p{i}", days_ago=20 - i)
    early = view(db, "shop@ybl")
    assert early.payer_count == 11
    assert early.shared_payer_peak is None

    for i in range(11):                       # a peer appears afterwards
        pay(db, "peer@ybl", f"p{i}", days_ago=0)
    assert early.payer_count == 11, "the earlier reading is a value, not a live view"
    assert view(db, "shop@ybl").shared_payer_peak == 11


# ── I-M. Availability and status ─────────────────────────────────────────────

def test_an_unknown_payee_is_unavailable_not_zero(db):
    row, result = graph_row(db, "never-seen@ybl", amount=100.0)
    assert row["available"] is False
    assert row["score"] is None and row["facts"] == []
    assert result["verdict"] in {"APPROVE", "WARN"}, "unknown is not fraud"


def test_a_registered_but_unobserved_payee_has_no_graph_evidence(db):
    """Registration is an identity claim and creates no edges."""
    db.execute("INSERT OR IGNORE INTO users (id, username, password_hash, upi_id, "
               "upi_verified, created_at) VALUES ('u9','u9','x','fresh@ybl',1,?)", (iso(0),))
    db.commit()
    row, _ = graph_row(db, "fresh@ybl", amount=100.0)
    assert row["available"] is False


def test_graph_unavailable_lowers_confidence_without_raising_risk(db):
    from backend.app.services.payee_check import check_payee

    for i in range(12):
        pay(db, "known@ybl", f"p{i}", days_ago=200 - i * 10)
    seen = check_payee("known@ybl", payer_id="u1", amount=500.0, conn=db)
    unseen = check_payee("unknown@ybl", payer_id="u1", amount=500.0, conn=db)

    assert seen["evidence_available"]["graph"] is True
    assert unseen["evidence_available"]["graph"] is False
    assert unseen["confidence_score"] < seen["confidence_score"]
    assert unseen["risk_score"] >= 0


def test_available_graph_evidence_without_overlap_scores_nothing(db):
    for i in range(12):
        pay(db, "solo@ybl", f"p{i}", days_ago=200 - i * 10)
    row, _ = graph_row(db, "solo@ybl", amount=500.0)
    assert row["available"] is True
    assert row["score"] == 0
    assert row["facts"] == []


def test_shape_is_reported_but_never_scored_by_the_graph_family(db):
    """payee_history already scores the shape. Scoring it again inflates the
    total even when the agreement bonus is correctly withheld, because the
    damped-max rule adds 0.4 of a second reading whatever tag it carries."""
    from backend.app.services.payee_check import check_payee

    for i in range(14):
        pay(db, "young@fastpay", f"p{i}", amount=4500, days_ago=2 - i * 0.1)
    result = check_payee("young@fastpay", payer_id="u1", amount=4500.0, conn=db)
    row = next(e for e in result["evidence"] if e["family"] == "graph")

    assert result["graph"]["shape_findings"], "reported for the reader"
    assert row["score"] == 0, "and scored by payee_history alone"
    assert "payee_shape" not in row["facts"]


# ── Read-path purity ─────────────────────────────────────────────────────────

def test_the_read_path_issues_no_writes_at_all(db):
    """No DDL, no edge mutation, no union-find path compression.

    Path compression is a legitimate optimisation and a write, and this path
    must not write: it also ran DDL on every check at one point, which broke
    outright against a database file on a network mount.
    """
    from backend.app.services.payee_check import check_payee

    for i in range(12):
        pay(db, "shop@ybl", f"p{i}")

    statements: list[str] = []
    db.set_trace_callback(statements.append)
    check_payee("shop@ybl", payer_id="u1", amount=500.0, conn=db)
    db.set_trace_callback(None)

    forbidden = ("CREATE", "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "REPLACE")
    offenders = [s for s in statements
                 if any(s.lstrip().upper().startswith(word) for word in forbidden)]
    assert not offenders, f"the read path wrote: {offenders}"


def test_component_size_does_not_compress_paths(db):
    from backend.app.services.graph_cache import component_size

    for i in range(20):
        pay(db, f"p{i}@ybl", f"payer{i}")
        pay(db, f"p{i}@ybl", "bridge")
    before = [tuple(r) for r in db.execute("SELECT * FROM graph_components ORDER BY node")]
    for i in range(20):
        component_size(db, f"p{i}@ybl")
    after = [tuple(r) for r in db.execute("SELECT * FROM graph_components ORDER BY node")]
    assert before == after, "the read variant rewrote the union-find"
