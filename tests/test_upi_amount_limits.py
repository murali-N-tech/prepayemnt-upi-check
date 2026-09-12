"""A UPI payment cannot be any amount you like.

NPCI caps a single UPI transaction at Rs 1,00,000 for P2P and standard merchant
payments, and Rs 5,00,000 for verified merchants in certain categories. Nothing
in this system enforced that. Measured before these tests existed:

    POST /predict {"amount": -5000}          -> 200, risk=0, "APPROVED"
    POST /predict {"amount": 1e12}           -> 200, scored as a real payment
    upi://pay?...&am=99999999                -> one info finding, "the amount
                                                is fixed at Rs 99,999,999.00"
    check_payee("shop@ybl", amount=9999999)  -> WARN

Every one of those is a fraud verdict about a payment that could not happen.
"""

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest

from backend.app.core.upi_limits import (
    cap_for,
    check_amount,
    describe_cap,
    merchant_cap,
    standard_cap,
)
from backend.app.services.payee_check import check_payee
from backend.app.services.upi_qr import parse_upi_target


# ── The caps themselves ──────────────────────────────────────────────────────

def test_the_standard_cap_is_one_lakh():
    assert standard_cap() == 100_000.0
    assert describe_cap(standard_cap()) == "Rs 1 lakh"


def test_the_higher_cap_needs_both_a_merchant_code_and_a_signature():
    """Not a free upgrade. A QR carrying only `mc` is trivially forged, so one
    without the other buys nothing - a pasted VPA or a phone number certainly
    does not establish that the payee is a verified merchant."""
    assert cap_for() == standard_cap()
    assert cap_for(merchant_code="5411") == standard_cap()
    assert cap_for(signed=True) == standard_cap()
    assert cap_for(merchant_code="5411", signed=True) == merchant_cap()


@pytest.mark.parametrize("amount", [0, -1, -5000, 0.001, float("inf"), float("nan")])
def test_an_amount_that_is_not_a_payment_is_refused(amount):
    assert check_amount(amount) is not None


@pytest.mark.parametrize("amount", [0.01, 1, 500, 25_000, 99_999.99, 100_000])
def test_every_amount_upi_can_carry_is_accepted(amount):
    assert check_amount(amount) is None


def test_above_the_standard_cap_is_refused_but_a_verified_merchant_is_not():
    assert check_amount(100_001) is not None
    assert check_amount(300_000) is not None
    assert check_amount(300_000, merchant_code="5411", signed=True) is None
    # Even a verified merchant has a ceiling.
    assert check_amount(600_000, merchant_code="5411", signed=True) is not None


def test_a_missing_amount_is_not_an_error():
    """The pre-payment screen sends no amount until the payer types one."""
    assert check_amount(None) is None


# ── The QR payload ───────────────────────────────────────────────────────────

def test_a_qr_demanding_more_than_upi_carries_is_a_critical_finding():
    """Previously this produced exactly one finding: "the amount is fixed at
    Rs 99,999,999.00 by the QR", severity info. A request no app can honour is
    not a payment request - it is a tampered or fabricated QR, which is the
    whole reason for parsing the payload."""
    q = parse_upi_target("upi://pay?pa=shop@ybl&pn=Shop&am=99999999")
    codes = {f.code: f.severity for f in q.findings}
    assert codes.get("amount_over_upi_limit") == "critical"


def test_a_signed_merchant_qr_may_carry_up_to_the_higher_cap():
    ok = parse_upi_target("upi://pay?pa=shop@ybl&pn=Shop&mc=5411&sign=abc&am=300000")
    assert "amount_over_upi_limit" not in {f.code for f in ok.findings}

    over = parse_upi_target("upi://pay?pa=shop@ybl&pn=Shop&mc=5411&sign=abc&am=600000")
    assert "amount_over_upi_limit" in {f.code for f in over.findings}


def test_an_unsigned_qr_gets_the_standard_cap():
    q = parse_upi_target("upi://pay?pa=shop@ybl&pn=Shop&mc=5411&am=300000")
    assert "amount_over_upi_limit" in {f.code for f in q.findings}


def test_a_qr_at_exactly_the_cap_is_fine():
    q = parse_upi_target("upi://pay?pa=shop@ybl&pn=Shop&am=100000")
    assert "amount_over_upi_limit" not in {f.code for f in q.findings}
    assert q.amount == 100_000.0


# ── The pre-payment check ────────────────────────────────────────────────────

def test_an_impossible_amount_blocks_rather_than_warns():
    """check_payee used to return WARN for Rs 99,99,999 - a considered-looking
    verdict on a payment UPI would refuse outright."""
    r = check_payee("shop@ybl", amount=9_999_999)
    assert r["decision"] == "BLOCK"
    assert "amount_over_upi_limit" in {f["code"] for f in r["findings"]}


def test_a_qr_over_the_limit_blocks_through_the_hard_block_list():
    r = check_payee("upi://pay?pa=shop@ybl&pn=Shop&am=10000000")
    assert r["decision"] == "BLOCK"
    assert r["headline"] == "Do not pay this"


def test_zero_means_not_typed_yet_and_is_not_a_violation():
    """A zero amount used to BLOCK under the code "amount_over_upi_limit",
    which was simply untrue: the pre-payment screen sends 0 before the payer
    fills the field in."""
    for amount in (None, 0, 0.0):
        r = check_payee("shop@ybl", amount=amount)
        assert "amount_over_upi_limit" not in {f["code"] for f in r["findings"]}
        assert r["decision"] != "BLOCK"


def test_an_amount_at_the_cap_is_allowed_through_the_check():
    r = check_payee("shop@ybl", amount=100_000)
    assert "amount_over_upi_limit" not in {f["code"] for f in r["findings"]}


# ── The simulator must generate only payments UPI could carry ────────────────

def test_the_simulator_never_generates_an_impossible_amount():
    from backend.ml.dataset import UPI_PER_TXN_CAP, generate

    df = generate(n_transactions=20_000, seed=11)
    a = df["amount"].to_numpy()
    assert a.min() > 0, "a non-positive amount is not a payment"
    assert a.max() <= UPI_PER_TXN_CAP, (
        f"generated Rs {a.max():,.2f}, above the Rs {UPI_PER_TXN_CAP:,.0f} cap"
    )


def test_the_simulator_covers_the_whole_legal_range_in_both_classes():
    """The real bug behind the hard-coded `amount > 70000` rule in /predict.

    Amounts topped out around Rs 61,000 - 3 rows in 120,000 above Rs 50,000 and
    NONE above Rs 70,000 - so the model never saw the top 30% of the legal UPI
    range and its prediction was flat at 0.4034 from Rs 5,000 to Rs 1,00,000.
    It could not tell an ordinary payment from a maxed-out drain, which is the
    signature of an account takeover.
    """
    from backend.ml.dataset import generate

    df = generate(n_transactions=60_000, seed=12)
    a = df["amount"].to_numpy()
    y = df["is_fraud"].to_numpy()

    for lo, hi in [(25_000, 50_000), (50_000, 70_000), (70_000, 100_001)]:
        band = (a >= lo) & (a < hi)
        assert (band & (y == 1)).sum() > 0, f"no fraud in Rs {lo}-{hi}"
        assert (band & (y == 0)).sum() > 0, (
            f"no LEGITIMATE payment in Rs {lo}-{hi} - if only fraud reaches the "
            f"top of the range, 'amount is large' becomes a near-perfect rule "
            f"and the dataset is leaking the label in a new shape"
        )


def test_a_large_amount_is_a_signal_not_a_giveaway():
    """Guards the leak this fix could easily have introduced. A first attempt
    left only 14 legitimate rows above Rs 70,000 against 120 fraudulent ones,
    making P(fraud | amount > 70k) = 0.90 against a 1.2% base rate - a property
    of a simulated population with nobody in it who pays rent, not a property
    of fraud."""
    from backend.ml.dataset import generate

    df = generate(n_transactions=60_000, seed=13)
    a = df["amount"].to_numpy()
    y = df["is_fraud"].to_numpy()

    high = a > 70_000
    assert high.sum() > 50, "too few high-value rows to say anything"
    posterior = float(y[high].mean())
    assert posterior > y.mean() * 3, (
        "a large amount should carry real signal; it does not"
    )
    assert posterior < 0.5, (
        f"P(fraud | amount > 70k) = {posterior:.2f}. Above a half, 'the amount "
        f"is large' is close to a deciding rule on its own, which is the shape "
        f"a leak takes."
    )
