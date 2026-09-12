"""The risk score has to move when the evidence moves.

Every finding used to contribute one of exactly four numbers - 0, 12, 35 or 70,
straight from SEVERITY_WEIGHT - so the whole system could only ever produce a
handful of final scores. Measured over 19 varied payments the output landed on
seven distinct values, and 40 came up in six of them: `payee_unseen` (warn, 12)
fires for every payee in a fresh database, and any single high-severity finding
beside it gives _combine(12, 35) = 35 + 0.4*12 = 39.8 -> 40.

That is not only cosmetic. It discarded information the system already had:
`large_to_unfamiliar` scored 35 for a Rs 25,000 payment and 35 for a Rs 99,000
one, because a continuous quantity had been flattened into a boolean.

Findings that can measure their own strength now carry a `weight`; genuinely
binary ones (an address either impersonates a bank or it does not) keep the
severity default.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

from backend.app.services.vpa import (
    SEVERITY_RANGE,
    SEVERITY_WEIGHT,
    VpaFinding,
    graded,
    total_weight,
)


# ── The weighting mechanism ─────────────────────────────────────────────────

def test_a_finding_without_a_weight_keeps_its_severity_default():
    for severity, expected in SEVERITY_WEIGHT.items():
        assert VpaFinding("x", severity, "m").scored() == float(expected)


def test_a_weight_cannot_escape_its_severity_band():
    """A finding presented as a warning must not score like a critical one, or
    the colour the user sees and the number driving the verdict disagree."""
    low, high = SEVERITY_RANGE["warn"]
    assert VpaFinding("x", "warn", "m", weight=999).scored() == high
    assert VpaFinding("x", "warn", "m", weight=-50).scored() == low


def test_graded_handles_a_descending_domain():
    """Several callers need one: for an account age, younger is worse, so the
    domain is written graded(30, 2, age_days, ...).

    The first version guarded with `high <= low`, which was meant for a
    zero-width range but caught every deliberately inverted one - so
    graded(30, 2, ...) returned the ceiling for any age above 2 days, a
    25-day-old account scored identically to a 1-day-old one, and mule_pattern
    came out at 94 for both.
    """
    assert graded(30, 2, 1, 60, 100) == pytest.approx(100)
    assert graded(30, 2, 40, 60, 100) == pytest.approx(60)
    mid = graded(30, 2, 16, 60, 100)
    assert 60 < mid < 100
    # Strictly monotonic in between, which is the whole point.
    ages = [graded(30, 2, a, 60, 100) for a in (28, 22, 16, 10, 4)]
    assert ages == sorted(ages), "a younger account must not score lower"


def test_graded_handles_an_ascending_domain():
    assert graded(10, 60, 5, 60, 100) == pytest.approx(60)
    assert graded(10, 60, 90, 60, 100) == pytest.approx(100)
    counts = [graded(10, 60, n, 60, 100) for n in (10, 25, 40, 60)]
    assert counts == sorted(counts)


def test_graded_survives_a_zero_width_domain():
    assert graded(5, 5, 9, 10, 40) == 40
    assert graded(5, 5, 1, 10, 40) == 10


def test_total_weight_is_capped_and_rounded():
    findings = [VpaFinding("a", "critical", "m"), VpaFinding("b", "critical", "m")]
    assert total_weight(findings) == 100
    assert isinstance(total_weight(findings), int)


# ── The amount is no longer a boolean ───────────────────────────────────────

def _fresh_check():
    """check_payee against an empty reputation store, as on a new deployment."""
    import backend.app.services.profile_store as store

    tmp = Path(tempfile.mkdtemp())
    store.DB_PATH = tmp / "t.db"
    store.DATA_DIR = tmp
    store._SCHEMA_DONE.clear()
    from backend.app.services.payee_check import check_payee

    return check_payee


def test_the_score_rises_with_the_amount():
    """Rs 25,000 and Rs 99,000 both produced exactly 40."""
    check_payee = _fresh_check()
    scores = [
        check_payee("shop@ybl", amount=a)["risk_score"]
        for a in (25_000, 40_000, 60_000, 80_000, 100_000)
    ]
    assert scores == sorted(scores), f"not monotonic: {scores}"
    assert len(set(scores)) >= 4, f"barely moves: {scores}"
    assert scores[-1] - scores[0] >= 15, f"too flat: {scores}"


def test_a_payment_at_the_upi_ceiling_to_a_stranger_escalates():
    """It used to come out WARN, the same as a Rs 25,000 payment."""
    check_payee = _fresh_check()
    small = check_payee("shop@ybl", amount=25_000)
    maxed = check_payee("shop@ybl", amount=100_000)
    assert small["decision"] == "WARN"
    assert maxed["decision"] in {"STEP_UP", "BLOCK"}


def test_an_unremarkable_payment_stays_approved():
    check_payee = _fresh_check()
    r = check_payee("shop@ybl", amount=500)
    assert r["decision"] == "APPROVE"


# ── The same pattern at different strengths ────────────────────────────────

def _seed_payees():
    import backend.app.services.profile_store as store

    tmp = Path(tempfile.mkdtemp())
    store.DB_PATH = tmp / "t.db"
    store.DATA_DIR = tmp
    store._SCHEMA_DONE.clear()

    from backend.app.services.payee_reputation import connect, record_payment

    def iso(days: float) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    conn = connect()
    # Blatant collection account: days old, dozens of one-shot payers, amounts
    # clustered on a single figure.
    for i in range(45):
        record_payment("mule@ybl", f"p{i}", 4999.0 + (i % 3),
                       at=iso(max(0.1, 3 - i * 0.05)), conn=conn, autocommit=False)
    # A new small shop: a month old, a dozen customers, none returned yet,
    # ordinary spread of amounts. Superficially the same shape, far weaker.
    for i in range(12):
        record_payment("newshop@ybl", f"n{i}", 500.0 + i * 300,
                       at=iso(25 - i), conn=conn, autocommit=False)
    # An established merchant.
    for i in range(300):
        record_payment("swiggy@ibl", f"c{i % 60}", 150.0 + (i * 37) % 900,
                       at=iso(400 - i), conn=conn, autocommit=False)
    conn.commit()
    return conn


def test_a_blatant_mule_outscores_a_merely_new_shop():
    """Both trip `mule_pattern`, which is one severity band, so both scored a
    flat 70 and both were BLOCKed - a false positive on every legitimate new
    business."""
    conn = _seed_payees()
    from backend.app.services.payee_reputation import assess_payee

    mule = assess_payee("mule@ybl", conn=conn)
    shop = assess_payee("newshop@ybl", conn=conn)

    assert mule.score > shop.score + 20, f"mule {mule.score} vs shop {shop.score}"
    assert mule.score >= 90
    assert shop.score < 70, "a month-old shop with a dozen customers is not a certainty"


def test_a_new_shop_is_verified_rather_than_blocked():
    conn = _seed_payees()
    from backend.app.services.payee_check import check_payee

    assert check_payee("mule@ybl", amount=4999, conn=conn)["decision"] == "BLOCK"
    assert check_payee("newshop@ybl", amount=4999, conn=conn)["decision"] == "STEP_UP"


def test_an_established_merchant_is_approved():
    conn = _seed_payees()
    from backend.app.services.payee_check import check_payee

    r = check_payee("swiggy@ibl", amount=4999, conn=conn)
    assert r["decision"] == "APPROVE"


# ── The distribution itself ────────────────────────────────────────────────

def test_the_score_does_not_collapse_onto_a_few_values():
    """The bug as the user met it: "whenever I check a payee the score shows 40".

    A spread of realistic payments must not pile up on one number. Asserting
    the shape of the distribution rather than any single score keeps this
    honest without pinning down figures that are policy and may be retuned.
    """
    check_payee = _fresh_check()
    cases = [
        dict(payload="shop@ybl"),
        dict(payload="shop@ybl", amount=500),
        dict(payload="shop@ybl", amount=25_000),
        dict(payload="shop@ybl", amount=60_000),
        dict(payload="shop@ybl", amount=99_000),
        dict(payload="9876543210"),
        dict(payload="9876543210", amount=30_000),
        dict(payload="upi://pay?pa=swiggy@ibl&pn=Swiggy&am=420"),
        dict(payload="upi://pay?pa=amitsharma123@ybl&pn=Ram%20Store&am=2500"),
        dict(payload="shop@ybl", intent="refund"),
        dict(payload="shop@ybl", intent="bill"),
        dict(payload="9876543210", intent="bill"),
        dict(payload="shop@ybl", intent="shop"),
        dict(payload="shop@ybl", intent="asked_to"),
        dict(payload="shop@ybl", intent="investment"),
        dict(payload="shop@ybl", intent="asked_to", amount=45_000),
        dict(payload="shop@ybl", message="hi please send the 500 for lunch"),
        dict(payload="shop@ybl", intent="refund", amount=50_000),
    ]
    scores = [check_payee(**kw)["risk_score"] for kw in cases]
    distinct = len(set(scores))
    most_common = max(scores.count(s) for s in set(scores))

    assert distinct >= 12, f"only {distinct} distinct scores across {len(scores)} payments: {scores}"
    assert most_common <= len(scores) // 3, (
        f"one score accounts for {most_common} of {len(scores)} payments: {sorted(scores)}"
    )
