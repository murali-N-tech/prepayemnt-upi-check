"""The pre-payment check.

Combines views of a payment that has not happened yet:

  1. the address itself   - is it valid, does it impersonate someone (vpa.py)
  2. the QR payload       - was the request tampered with (upi_qr.py)
  3. the payee's history  - what has everyone else's money done here
                            (payee_reputation.py)
  4. the stated purpose   - does it contradict the payee (intent.py)
  5. the pressure         - what does the message that caused this say
                            (coercion.py)

and, when the payer is known, their own behaviour baseline. The output is a
four-way decision rather than approve/block, because the useful answer for a
pre-payment product is usually the middle: "this payee is nine days old and
24 people have paid it once each - are you sure?"

Streams 4 and 5 exist because of a measured gap. The payer-behaviour and
payee-graph streams together catch 58.4% of social-engineering fraud at a 1%
false-positive budget. The rest is missed structurally: in that fraud class
the payer behaves normally, because they were persuaded. The evidence is not
in the transaction - it is in the instruction that produced it, and in the
mismatch between what the payer thinks they are doing and who actually
receives the money.

The combination rule matters as much as the streams. A single stream must not
reach BLOCK on weak evidence, but independent streams AGREEING is much stronger
than any of them alone - so agreement across families earns a bonus, while two
findings from the same family do not.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from backend.app.services.coercion import analyse_message
from backend.app.services.intent import analyse_intent
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


# Corroboration across independent evidence families. Each family gets one
# vote at most, so a message with four scam patterns still counts once: what
# is being rewarded is INDEPENDENT streams agreeing, not volume.
AGREEMENT_BONUS = {2: 6, 3: 14, 4: 22}


def _agreement_bonus(family_scores: dict[str, int], threshold: int = 20) -> tuple[int, list[str]]:
    agreeing = sorted(name for name, score in family_scores.items() if score >= threshold)
    return AGREEMENT_BONUS.get(len(agreeing), 0), agreeing


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
    intent: Optional[str] = None,
    message: Optional[str] = None,
) -> dict[str, Any]:
    """`payload` is a scanned QR, a pasted UPI ID, or a phone number.

    `intent` is what the payer says they are doing; `message` is the text that
    prompted the payment. Both optional - every existing caller keeps working,
    and their absence is never treated as evidence that a payment is safe.
    """
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

    # ── The stated purpose, checked against who actually gets the money ──────
    is_phone_payee = qr.kind == "phone" or bool(
        qr.vpa_analysis and getattr(qr.vpa_analysis, "from_phone", False)
    )
    intent_result = analyse_intent(
        intent,
        merchant_code=qr.merchant_code,
        is_phone_payee=is_phone_payee,
        established=established,
        payee_name=qr.payee_name,
    )
    findings.extend(intent_result.findings)

    # ── The pressure behind the payment ─────────────────────────────────────
    coercion = analyse_message(message)
    coercion_findings = [
        VpaFinding(
            f"message_{f.code}",
            f.severity,
            f.message + (f': "{f.quote}"' if f.quote else ""),
        )
        for f in coercion.findings
    ]
    # The message score is the fitted probability, not a sum of severities: the
    # whole point of fitting it was that the patterns are worth different
    # amounts, and several weak ones must not add up to a strong one.
    coercion_score = coercion.score if coercion.supplied else 0
    findings.extend(coercion_findings)
    if coercion.language_note:
        findings.append(VpaFinding("message_language", "info", coercion.language_note))

    family_scores = {
        "address_and_qr": qr.score,
        "payee_history": reputation.score if reputation else 0,
        "amount_context": amount_score,
        "stated_intent": intent_result.score,
        "message_pressure": coercion_score,
    }
    bonus, agreeing = _agreement_bonus(family_scores)

    base = _combine(*family_scores.values())
    score = int(min(99, base + bonus))
    if bonus:
        findings.append(VpaFinding(
            "streams_agree", "high",
            f"{len(agreeing)} independent checks flagged this payment "
            f"({', '.join(a.replace('_', ' ') for a in agreeing)}). Any one of them "
            f"alone would be worth a second look; together they are the reason for "
            f"this verdict."
        ))

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
        "intent": intent_result.as_dict(),
        "message_pressure": coercion.as_dict(),
        "component_scores": family_scores,
        "agreement": {"families": agreeing, "bonus": bonus},
        "findings": [
            {"code": f.code, "severity": f.severity, "message": f.message} for f in findings
        ],
        "checked_by": payer_id,
    }
