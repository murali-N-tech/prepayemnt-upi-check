"""Status describes evidence, never trust.

The failure mode being guarded against is the one every identity layer drifts
into: registered accounts start getting the benefit of the doubt, and since
registering is the cheapest thing a fraudster can do, the identity layer
becomes the attack surface. None of these tests check a score, because status
is not allowed to produce one.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.app.core.entity_status import (
    MIN_PAYERS_FOR_SHAPE,
    EntityStatus,
    EvidenceLevel,
    RelationshipStatus,
    ensure_schema,
    record_verification,
    resolve_payee,
    resolve_relationship,
)


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE payee_reputation (vpa TEXT PRIMARY KEY, payment_count INTEGER,
                                       first_seen TEXT);
        CREATE TABLE payee_payers (vpa TEXT, payer_id TEXT, payments INTEGER,
                                   first_at TEXT, last_at TEXT,
                                   PRIMARY KEY (vpa, payer_id));
        CREATE TABLE users (id TEXT PRIMARY KEY, upi_id TEXT);
    """)
    ensure_schema(c)
    yield c
    c.close()


def observe(conn, vpa, payers, payments_each=1, first_seen="2026-01-01T00:00:00"):
    conn.execute("INSERT INTO payee_reputation VALUES (?,?,?)",
                 (vpa, payers * payments_each, first_seen))
    for i in range(payers):
        conn.execute("INSERT INTO payee_payers VALUES (?,?,?,?,?)",
                     (vpa, f"payer_{i}", payments_each, first_seen, first_seen))


# ── The four statuses ────────────────────────────────────────────────────────

def test_an_address_nobody_has_seen_is_unknown(conn):
    identity = resolve_payee("stranger@ybl", conn)
    assert identity.status is EntityStatus.UNKNOWN
    assert identity.history_available is False
    # Not zero. Nobody counted nothing; nobody counted at all.
    assert identity.observed_payers is None
    assert identity.observed_payments is None


def test_an_address_in_contributed_data_is_observed(conn):
    observe(conn, "shop@ybl", payers=40, payments_each=6)
    identity = resolve_payee("shop@ybl", conn)
    assert identity.status is EntityStatus.OBSERVED
    assert identity.history_available is True
    assert identity.observed_payers == 40


def test_an_address_with_an_account_here_is_registered(conn):
    conn.execute("INSERT INTO users VALUES ('u1', 'MyShop@Ybl')")
    assert resolve_payee("myshop@ybl", conn).status is EntityStatus.REGISTERED


def test_verification_outranks_registration(conn):
    conn.execute("INSERT INTO users VALUES ('u1', 'shop@ybl')")
    observe(conn, "shop@ybl", payers=30)
    record_verification("shop@ybl", verified_by="npci-sandbox", method="test", conn=conn)
    assert resolve_payee("shop@ybl", conn).status is EntityStatus.VERIFIED


# ── Status is not a verdict ──────────────────────────────────────────────────

def test_status_carries_no_score(conn):
    """Nothing in the identity object may be read as risk. If a score ever
    appears here, something downstream will start using it as one."""
    observe(conn, "shop@ybl", payers=30)
    fields = resolve_payee("shop@ybl", conn).as_dict()
    for forbidden in ("score", "risk", "band", "verdict", "trusted", "safe"):
        assert forbidden not in fields


def test_registration_does_not_imply_history(conn):
    """An account created this morning has an identity and no behaviour.

    Conflating the two is how "registered" becomes "trusted": the status says
    somebody filled in a form, and the evidence layer would read that as a
    reason to believe the payee.
    """
    conn.execute("INSERT INTO users VALUES ('u1', 'brandnew@ybl')")
    identity = resolve_payee("brandnew@ybl", conn)
    assert identity.status is EntityStatus.REGISTERED
    assert identity.history_available is False
    assert EntityStatus.REGISTERED.has_history is False


def test_verified_does_not_imply_history(conn):
    record_verification("verified@ybl", verified_by="provider", method="kyc", conn=conn)
    identity = resolve_payee("verified@ybl", conn)
    assert identity.status is EntityStatus.VERIFIED
    assert identity.history_available is False


# ── The floor on what counts as history ──────────────────────────────────────

def test_too_few_payers_is_not_history(conn):
    """Two payers who paid once each give a repeat ratio of exactly 0.0, which
    is the signature of a collection account and is in fact an empty sample.
    Reporting it as measured evidence claims a precision the data lacks."""
    observe(conn, "thin@ybl", payers=MIN_PAYERS_FOR_SHAPE - 1)
    identity = resolve_payee("thin@ybl", conn)
    assert identity.status is EntityStatus.OBSERVED, "we have seen it"
    assert identity.history_available is False, "but not enough of it to read shape"


def test_enough_payers_is_history(conn):
    observe(conn, "thick@ybl", payers=MIN_PAYERS_FOR_SHAPE)
    assert resolve_payee("thick@ybl", conn).history_available is True


# ── Relationship ─────────────────────────────────────────────────────────────

def test_an_unauthenticated_caller_gets_unknown_not_new(conn):
    """NEW asserts we looked and found nothing. UNKNOWN admits we could not
    look. Collapsing them lets an unauthenticated request pass itself off as a
    verified first payment."""
    status, detail = resolve_relationship("shop@ybl", None, conn)
    assert status is RelationshipStatus.UNKNOWN
    assert detail is None


def test_a_first_payment_is_new_with_a_measured_zero(conn):
    observe(conn, "shop@ybl", payers=20)
    status, detail = resolve_relationship("shop@ybl", "somebody_else", conn)
    assert status is RelationshipStatus.NEW
    assert detail["transaction_count"] == 0, "measured: we looked and there are none"


def test_a_returning_payer_is_established(conn):
    observe(conn, "shop@ybl", payers=20, payments_each=3)
    status, detail = resolve_relationship("shop@ybl", "payer_4", conn)
    assert status is RelationshipStatus.ESTABLISHED
    assert detail["transaction_count"] == 3


def test_relationship_is_scoped_to_the_asking_payer(conn):
    """payer_4's history with this payee must not become payer_9's."""
    observe(conn, "shop@ybl", payers=5, payments_each=7)
    _, mine = resolve_relationship("shop@ybl", "payer_4", conn)
    other, _ = resolve_relationship("shop@ybl", "not_a_payer_here", conn)
    assert mine["transaction_count"] == 7
    assert other is RelationshipStatus.NEW


def test_evidence_level_values_are_the_documented_three():
    assert {e.value for e in EvidenceLevel} == {"FULL", "PARTIAL", "MINIMAL"}
    assert {e.value for e in EntityStatus} == {"REGISTERED", "OBSERVED", "VERIFIED", "UNKNOWN"}
