"""The pre-payment check.

Combines three views of a payment that has not happened yet:

  1. the address itself   - is it valid, does it impersonate someone (vpa.py)
  2. the QR payload       - was the request tampered with (upi_qr.py)
  3. the payee's history  - what has everyone else's money done here
                            (payee_reputation.py)

and, when the payer is known, their own behaviour baseline. The output is a
four-way decision rather than approve/block, because the useful answer for a
pre-payment product is usually the middle: "this payee is nine days old and
24 people have paid it once each - are you sure?"
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from backend.app.services.payee_reputation import assess_payee, payee_key
from backend.app.services.upi_qr import parse_upi_target
from backend.app.services.vpa import SEVERITY_WEIGHT, VpaFinding

# Decision thresholds. Deliberately named, because a reviewer should be able to
# argue with them: they are policy, not a model output.
BLOCK_AT = 70
STEP_UP_AT = 45
WARN_AT = 22

SEVERITY_ORDER = {"info": 0, "warn": 1, "high": 2, "critical": 3}

# Above this, a payment to a payee nobody has a history with is worth stopping
# for even when nothing else looks wrong.
LARGE_AMOUNT = 25_000

# Findings that decide the outcome on their own, whatever the arithmetic says.
HARD_BLOCK = {"payee_blocked", "vpa_malformed", "not_a_payment_link", "no_payee", "empty"}


def _combine(*scores: int) -> int:
    """Strongest signal leads; the others add a damped amount.

    Straight addition saturates on any two moderate signals, and a plain max
    throws away corroboration. This keeps one strong signal decisive while
    letting a second one push the result up.
    """
    ordered = sorted((s for s in scores if s), reverse=True)
    if not ordered:
        return 0
    total = ordered[0] + sum(s * 0.4 for s in ordered[1:])
    return int(min(99, round(total)))


def _decide(score: int, findings: list[VpaFinding]) -> str:
    if any(f.code in HARD_BLOCK for f in findings):
        return "BLOCK"
    if score >= BLOCK_AT:
        return "BLOCK"
    if score >= STEP_UP_AT:
        return "STEP_UP"
    if score >= WARN_AT:
        return "WARN"
    return "APPROVE"


HEADLINES = {
    "APPROVE": "Nothing suspicious found",
    "WARN": "Worth a second look before you pay",
    "STEP_UP": "Verify the payee before sending money",
    "BLOCK": "Do not pay this",
}


def check_payee(
    payload: str,
    payer_id: Optional[str] = None,
    amount: Optional[float] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """`payload` is a scanned QR, a pasted UPI ID, or a phone number."""
    qr = parse_upi_target(payload)

    key = payee_key(qr.payee_vpa, qr.payee_name)
    reputation = assess_payee(key, conn=conn) if key else None

    findings: list[VpaFinding] = list(qr.all_findings)
    if reputation:
        findings.extend(reputation.findings)

    # Size matters when the payee is a stranger. A small payment to an unknown
    # address is how most people meet a new merchant; a large one is how most
    # people lose money.
    amount_findings: list[VpaFinding] = []
    effective_amount = qr.amount if qr.amount is not None else amount
    established = bool(
        reputation and any(f.code == "payee_established" for f in reputation.findings)
    )
    if effective_amount and effective_amount >= LARGE_AMOUNT and not established:
        amount_findings.append(
            VpaFinding("large_to_unfamiliar", "high",
                       f"Rs {effective_amount:,.0f} to a payee with no established "
                       f"history here. Confirm who you are paying first.")
        )
    findings.extend(amount_findings)

    amount_score = min(100, sum(SEVERITY_WEIGHT[f.severity] for f in amount_findings))
    score = _combine(qr.score, reputation.score if reputation else 0, amount_score)
    decision = _decide(score, findings)

    findings.sort(key=lambda f: -SEVERITY_ORDER[f.severity])

    return {
        "input": payload,
        "input_kind": qr.kind,
        "payee": {
            "vpa": qr.payee_vpa,
            "key": key,
            "display_name": qr.payee_name or (reputation.display_name if reputation else None),
            "valid": bool(qr.vpa_analysis and qr.vpa_analysis.valid),
            "handle_type": qr.vpa_analysis.handle_type if qr.vpa_analysis else "unknown",
            "impersonates": qr.vpa_analysis.impersonates if qr.vpa_analysis else None,
        },
        "request": {
            "amount": qr.amount if qr.amount is not None else amount,
            "amount_locked": qr.amount_locked,
            "note": qr.note,
            "merchant_code": qr.merchant_code,
            "signed": qr.signed,
        },
        "reputation": reputation.as_dict() if reputation else None,
        "risk_score": score,
        "decision": decision,
        "headline": HEADLINES[decision],
        "component_scores": {
            "address_and_qr": qr.score,
            "payee_history": reputation.score if reputation else 0,
            "amount_context": amount_score,
        },
        "findings": [
            {"code": f.code, "severity": f.severity, "message": f.message} for f in findings
        ],
        "checked_by": payer_id,
    }
