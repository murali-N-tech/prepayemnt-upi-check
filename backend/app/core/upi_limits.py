"""What a UPI payment is allowed to be.

One place for the NPCI per-transaction caps, because four different parts of
this system were each assuming something different - and none of them was
enforcing anything at all. Measured before this file existed:

    POST /predict  {"amount": -5000}         -> 200, risk=0, "APPROVED"
    POST /predict  {"amount": 1000000000000} -> 200, scored as a real payment
    upi://pay?...&am=99999999                -> parsed, "amount is fixed at
                                                Rs 99,999,999.00 by the QR"

A payment of minus five thousand rupees is not a thing, and one lakh crore
cannot move over UPI. Scoring them produces a fraud verdict about a payment
that could never happen, which is worse than an error: the user is told
"APPROVED".

The caps (NPCI, in force since 15 September 2025)
------------------------------------------------
  P2P and standard P2M          Rs 1,00,000 per transaction
  Verified merchants in certain
  categories - insurance,
  capital markets, travel,
  education, healthcare,
  collections, credit-card
  bills, tax and GeM            Rs 5,00,000 per transaction

Banks may set lower limits inside these, and NPCI revises them, so both are
overridable from the environment rather than frozen in code:

    UPI_MAX_AMOUNT=100000            # the default cap
    UPI_MAX_AMOUNT_MERCHANT=500000   # verified merchants only

Which cap applies
-----------------
The higher one is not a free upgrade: it is for a VERIFIED merchant, and the
only evidence this system has of that is what the QR carries - a merchant
category code and a signature. A pasted UPI ID, a phone number, or an unsigned
QR gets the standard cap, because nothing has established it is a merchant at
all. That is deliberately conservative: the failure mode of guessing wrong here
is accepting an amount UPI would reject.
"""

from __future__ import annotations

from typing import Optional

from backend.app.core.config import get

# Below this nothing is a payment. Not zero - UPI has no zero-rupee transfer -
# and certainly not negative.
MIN_AMOUNT = 0.01


def _money(name: str, default: float) -> float:
    try:
        value = float(str(get(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def standard_cap() -> float:
    """P2P and ordinary merchant payments."""
    return _money("UPI_MAX_AMOUNT", 100_000.0)


def merchant_cap() -> float:
    """Verified merchants in the higher-limit categories."""
    return max(_money("UPI_MAX_AMOUNT_MERCHANT", 500_000.0), standard_cap())


def cap_for(merchant_code: Optional[str] = None, signed: bool = False) -> float:
    """The cap that applies to this payee.

    Both a category code and a signature, or the standard cap. An individual
    scammer's QR carries neither, and a QR that carries only an `mc` with no
    signature is trivially forged - so one without the other buys nothing.
    """
    if merchant_code and signed:
        return merchant_cap()
    return standard_cap()


def describe_cap(cap: float) -> str:
    """How to say the cap in a sentence, in Indian numbering."""
    if cap >= 100_000 and cap % 100_000 == 0:
        lakh = int(cap // 100_000)
        return f"Rs {lakh} lakh"
    return f"Rs {cap:,.0f}"


def check_amount(
    amount: Optional[float],
    merchant_code: Optional[str] = None,
    signed: bool = False,
) -> Optional[str]:
    """None if this amount could be a real UPI payment, else why not.

    Returns a message rather than raising, so a request handler can turn it
    into a 422 and the payee check can turn the same finding into evidence.
    """
    if amount is None:
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return "That amount is not a number."

    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return "That amount is not a number."
    if value < 0:
        return "An amount cannot be negative."
    if value < MIN_AMOUNT:
        return "An amount has to be more than zero."

    cap = cap_for(merchant_code, signed)
    if value > cap:
        limit = describe_cap(cap)
        extra = (
            ""
            if cap > standard_cap()
            else f" Only verified merchants in certain categories "
                 f"({describe_cap(merchant_cap())}) can take more."
        )
        return (
            f"UPI does not carry more than {limit} in one payment, so "
            f"Rs {value:,.2f} cannot be a UPI transaction.{extra}"
        )
    return None
