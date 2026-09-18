"""Graph features maintained by observation, read by the payment check.

The split these tests hold in place:

    POST_PAYMENT_OBSERVATION  writes. One payee's shape is recomputed from its
                              own edges, and one union merges two components.
                              Both inside the transaction that wrote the edge.

    PRE_PAYMENT_CHECK         reads. Two indexed lookups and one bounded
                              two-hop query. No DDL, no rebuild, no writes of
                              any kind - checking a payment must not change
                              anything, including a cache.

The thing worth stating about why component size is incremental at all: an
observation can only ADD an edge, and adding an edge can only MERGE
components. That is what makes union-find sufficient. Nothing here removes an
edge, and if anything ever does, this approach stops being correct.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import backend.app.services.profile_store as store


def iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


@pytest.fixture()
def db(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(store, "DB_PATH", tmp / "graph.db")
    monkeypatch.setattr(store, "DATA_DIR", tmp)
    store._SCHEMA_DONE.clear()
    from backend.app.services.payee_reputation import connect

    conn = connect()
    yield conn
    conn.close()
    store._SCHEMA_DONE.clear()


def pay(conn, payee, payer, amount=1000.0, days_ago=1.0):
    from backend.app.services.payee_reputation import record_payment

    record_payment(payee, payer_id=payer, amount=amount, at=iso(days_ago), conn=conn)


def view(conn, payee):
    from backend.app.services.graph_cache import graph_view

    return graph_view(conn, payee)


# ── 1-9. Incremental maintenance ─────────────────────────────────────────────

def test_a_new_payee_and_a_new_edge_create_the_cache(db):
    assert view(db, "shop@ybl").available is False
    pay(db, "shop@ybl", "alice")
    v = view(db, "shop@ybl")
    assert v.available is True
    assert v.payer_count == 1 and v.repeat_payer_count == 0
    assert v.component_size == 2, "one payer and one payee are one component"


def test_an_existing_edge_increments_rather_than_duplicating(db):
    pay(db, "shop@ybl", "alice", days_ago=5)
    pay(db, "shop@ybl", "alice", days_ago=1)
    v = view(db, "shop@ybl")
    assert v.payer_count == 1, "same payer, still one distinct payer"
    assert v.repeat_payer_count == 1, "and now a repeat one"
    assert v.repeat_ratio == 1.0


def test_a_new_distinct_payer_widens_the_payer_count(db):
    pay(db, "shop@ybl", "alice")
    pay(db, "shop@ybl", "bob")
    v = view(db, "shop@ybl")
    assert v.payer_count == 2 and v.repeat_payer_count == 0
    assert v.component_size == 3


def test_a_repeat_payer_moves_the_ratio_not_the_count(db):
    for who in ("a", "b", "c", "d"):
        pay(db, "shop@ybl", who)
    assert view(db, "shop@ybl").repeat_ratio == 0.0
    pay(db, "shop@ybl", "a")
    v = view(db, "shop@ybl")
    assert v.payer_count == 4 and v.repeat_payer_count == 1
    assert v.repeat_ratio == 0.25


def test_the_arrival_window_tracks_when_payers_first_appeared(db):
    pay(db, "shop@ybl", "early", days_ago=40)
    pay(db, "shop@ybl", "late", days_ago=10)
    v = view(db, "shop@ybl")
    assert 29 < v.arrival_span_days < 31, "first-seen to first-seen"

    # A returning payer extends activity but NOT the arrival window - that is
    # the distinction that stops one late repeat silencing a burst finding.
    before = v.arrival_span_days
    pay(db, "shop@ybl", "early", days_ago=0)
    after = view(db, "shop@ybl")
    assert after.arrival_span_days == pytest.approx(before, abs=0.01)
    assert after.lifespan_days > after.arrival_span_days


def test_an_arrival_burst_is_reported_as_shape(db):
    for i in range(14):
        pay(db, "mule@fastpay", f"p{i}", amount=4500, days_ago=2 - i * 0.1)
    v = view(db, "mule@fastpay")
    assert v.payer_count == 14 and v.repeat_ratio == 0.0
    assert any("paid twice" in f for f in v.shape_findings)
    assert any("arrived within" in f for f in v.shape_findings)


def test_the_payee_aggregate_and_the_edge_table_agree(db):
    for i in range(9):
        pay(db, "shop@ybl", f"p{i}")
    pay(db, "shop@ybl", "p0")
    edges = db.execute(
        "SELECT COUNT(*) AS n, SUM(payments) AS p FROM payee_payers WHERE vpa = 'shop@ybl'"
    ).fetchone()
    cached = db.execute(
        "SELECT payer_count, payments FROM payee_graph_cache WHERE vpa = 'shop@ybl'"
    ).fetchone()
    assert cached["payer_count"] == edges["n"]
    assert cached["payments"] == edges["p"]


def test_the_relationship_row_is_updated_with_the_graph(db):
    from backend.app.services.payee_reputation import payer_has_paid

    assert payer_has_paid("shop@ybl", "alice", conn=db) is False
    pay(db, "shop@ybl", "alice")
    assert payer_has_paid("shop@ybl", "alice", conn=db) is True


def test_components_merge_when_a_payer_bridges_two_payees(db):
    pay(db, "shopA@ybl", "alice")
    pay(db, "shopB@ybl", "bob")
    assert view(db, "shopA@ybl").component_size == 2
    assert view(db, "shopB@ybl").component_size == 2

    pay(db, "shopB@ybl", "alice")          # alice now bridges them
    assert view(db, "shopA@ybl").component_size == 4
    assert view(db, "shopB@ybl").component_size == 4


# ── 10-11. Atomicity and concurrency ─────────────────────────────────────────

def test_a_failed_update_rolls_back_every_structure(db, monkeypatch):
    """The edge, the reputation row and the graph must move together.

    Committing an edge and failing its cache would leave a payee whose shape
    says it has fewer payers than the edge table holds, and nothing downstream
    could detect the disagreement.
    """
    import backend.app.services.payee_reputation as rep

    pay(db, "shop@ybl", "alice")
    before_edges = db.execute("SELECT COUNT(*) FROM payee_payers").fetchone()[0]
    before_cache = view(db, "shop@ybl").payer_count

    def explode(*a, **k):
        raise RuntimeError("graph update failed")

    monkeypatch.setattr(rep, "observe_edge", explode)
    with pytest.raises(RuntimeError):
        pay(db, "shop@ybl", "bob")

    assert db.execute("SELECT COUNT(*) FROM payee_payers").fetchone()[0] == before_edges
    assert view(db, "shop@ybl").payer_count == before_cache


def test_concurrent_observations_do_not_corrupt_the_aggregates(db):
    """Each thread opens its own connection, as the server would."""
    from backend.app.services.payee_reputation import connect, record_payment

    errors: list[Exception] = []

    def worker(n: int):
        try:
            own = connect()
            try:
                for i in range(6):
                    record_payment("busy@ybl", payer_id=f"t{n}_{i}", amount=100.0,
                                   at=iso(1), conn=own)
            finally:
                own.close()
        except Exception as exc:                       # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    edges = db.execute(
        "SELECT COUNT(*) FROM payee_payers WHERE vpa = 'busy@ybl'").fetchone()[0]
    cached = db.execute(
        "SELECT payer_count FROM payee_graph_cache WHERE vpa = 'busy@ybl'").fetchone()[0]
    assert edges == 24
    assert cached == edges, "the cache must not drift from the edges under concurrency"


# ── 12-14. The read path ─────────────────────────────────────────────────────

def test_a_pre_payment_check_mutates_nothing(db):
    from backend.app.services.payee_check import check_payee

    for i in range(12):
        pay(db, "mule@fastpay", f"p{i}", amount=4500, days_ago=2 - i * 0.1)

    def snapshot():
        return {
            table: db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in ("payee_reputation", "payee_payers",
                          "payee_graph_cache", "graph_components")
        }

    before = {k: [tuple(r) for r in v] for k, v in snapshot().items()}
    for _ in range(3):
        check_payee("mule@fastpay", payer_id="u1", amount=4500.0, conn=db)
    after = {k: [tuple(r) for r in v] for k, v in snapshot().items()}
    assert before == after, "checking a payment changed stored state"


def test_a_pre_payment_check_does_not_rebuild_the_graph(db, monkeypatch):
    """Guards the specific mistake this work exists to avoid: making graph
    evidence available by calling the dashboard's full rebuild."""
    import backend.app.services.fraud_graph as fg
    from backend.app.services.payee_check import check_payee

    for name in ("load_edges", "build_graph", "detect_rings", "graph_summary",
                 "suspicious_payees"):
        monkeypatch.setattr(fg, name, lambda *a, **k: pytest.fail(
            f"fraud_graph.{name} was called from the pre-payment path"))

    for i in range(12):
        pay(db, "mule@fastpay", f"p{i}", amount=4500, days_ago=1)
    check_payee("mule@fastpay", payer_id="u1", amount=4500.0, conn=db)


def test_the_read_path_stays_bounded_as_the_graph_grows(db):
    """The query count must not scale with the store."""
    from backend.app.services.payee_check import check_payee

    class Counter:
        def __init__(self): self.n = 0
        def __call__(self, _stmt): self.n += 1

    for i in range(10):
        pay(db, "small@ybl", f"s{i}")
    db.set_trace_callback(counter := Counter())
    check_payee("small@ybl", payer_id="u1", amount=500.0, conn=db)
    small = counter.n
    db.set_trace_callback(None)

    for i in range(400):
        pay(db, f"other{i % 40}@ybl", f"bulk{i}")
    db.set_trace_callback(counter := Counter())
    check_payee("small@ybl", payer_id="u1", amount=500.0, conn=db)
    db.set_trace_callback(None)
    assert counter.n <= small + 2, f"{small} -> {counter.n} queries as the graph grew"


def test_features_never_use_observations_from_after_the_payment(db):
    """Temporal correctness. The cache is a running aggregate, so the guard is
    that a later observation cannot retroactively change an earlier reading -
    the check reads the store as it stands, and nothing back-dates."""
    for i in range(11):
        pay(db, "shop@ybl", f"p{i}", days_ago=20 - i)
    early = view(db, "shop@ybl")

    # Something that happens afterwards.
    for i in range(30):
        pay(db, "shop@ybl", f"later{i}", days_ago=0)
    late = view(db, "shop@ybl")

    assert late.payer_count > early.payer_count
    assert early.payer_count == 11, "the earlier reading is not rewritten"
    assert late.arrival_span_days >= early.arrival_span_days


# ── 15-20. Availability and facts ────────────────────────────────────────────

def test_an_unknown_payee_reports_graph_unavailable(db):
    from backend.app.services.payee_check import check_payee

    row = next(e for e in check_payee("never-seen@ybl", amount=100.0, conn=db)["evidence"]
               if e["family"] == "graph")
    assert row["available"] is False
    assert row["score"] is None, "null, never 0 - no position is not the origin"
    assert row["facts"] == []
    assert "never been observed" in row["unavailable_because"]


def test_an_observed_payee_reports_graph_available(db):
    from backend.app.services.payee_check import check_payee

    for i in range(12):
        pay(db, "shop@ybl", f"p{i}")
    row = next(e for e in check_payee("shop@ybl", amount=100.0, conn=db)["evidence"]
               if e["family"] == "graph")
    assert row["available"] is True
    assert row["score"] is not None


def test_a_registered_payee_with_no_observations_still_has_no_graph(db):
    """Registration is an identity claim. It creates no edges, so it creates
    no graph position, and the two must not be conflated."""
    from backend.app.services.payee_check import check_payee

    db.execute("INSERT OR IGNORE INTO users (id, username, password_hash, upi_id, "
               "upi_verified, created_at) VALUES ('u9','u9','x','fresh@ybl',1,?)",
               (iso(0),))
    db.commit()
    row = next(e for e in check_payee("fresh@ybl", amount=100.0, conn=db)["evidence"]
               if e["family"] == "graph")
    assert row["available"] is False


def test_graph_position_is_not_emitted_merely_because_a_graph_exists(db):
    """An ordinary observed payee has a position in the graph like every other
    node. That is not a finding, and tagging it would manufacture
    corroboration out of the system having a graph at all."""
    from backend.app.services.payee_check import check_payee

    for i in range(12):
        pay(db, "shop@ybl", f"p{i}", days_ago=200 - i * 10)
    row = next(e for e in check_payee("shop@ybl", amount=100.0, conn=db)["evidence"]
               if e["family"] == "graph")
    assert row["available"] is True
    assert "graph_position" not in row["facts"]


def test_graph_position_is_emitted_when_payers_are_actually_shared(db):
    """Two addresses drawing on the same pool of one-shot payers. This is the
    one thing the graph family scores, because it is the one thing no other
    family can see."""
    from backend.app.services.payee_check import check_payee

    for i in range(10):
        pay(db, "collectA@fastpay", f"shared{i}", amount=4500, days_ago=2)
        pay(db, "collectB@fastpay", f"shared{i}", amount=4500, days_ago=2)

    v = view(db, "collectA@fastpay")
    assert v.shared_payer_peak == 10 and v.overlap_with == "collectb@fastpay"
    assert v.position_findings

    row = next(e for e in check_payee("collectA@fastpay", amount=4500.0, conn=db)["evidence"]
               if e["family"] == "graph")
    assert row["facts"] == ["graph_position"]
    assert row["score"] > 0


def test_graph_shape_findings_do_not_score_twice(db):
    """The reputation family already scores the payee's shape. The graph
    family reports it for the reader and weights it at zero, because the
    damped-max rule adds 0.4 of a second reading whatever tag it carries - and
    a legitimate new shop went from STEP_UP to BLOCK on exactly that."""
    from backend.app.services.payee_check import check_payee

    for i in range(12):
        pay(db, "newshop@ybl", f"n{i}", amount=500.0 + i * 300, days_ago=25 - i)

    result = check_payee("newshop@ybl", amount=4999.0, conn=db)
    graph_row = next(e for e in result["evidence"] if e["family"] == "graph")
    assert graph_row["available"] is True
    assert graph_row["score"] == 0, "shape is reported here, not scored here"
    assert result["graph"]["shape_findings"], "and it IS reported"
    assert result["decision"] == "STEP_UP"
