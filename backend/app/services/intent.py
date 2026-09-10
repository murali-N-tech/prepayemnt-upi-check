"""What the payer says they are doing, checked against who they are paying.

This is the cheapest signal in the whole system and one of the most useful,
because fraud is very often a CONTRADICTION rather than an anomaly. Paying an
individual's UPI ID is completely normal. Paying an individual's UPI ID while
believing you are paying an electricity bill is not - and no amount of payer
behaviour modelling can see that, because the payer's behaviour is identical
in both cases. Only the stated purpose separates them.

The intents are deliberately few and phrased as a person would say them. The
last one, "someone asked me to", is the important one: it is the payer
reporting the social-engineering setup themselves, and it should never be
treated as neutral.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from backend.app.services.vpa import VpaFinding

INTENTS: dict[str, str] = {
    "bill": "Paying a bill",
    "shop": "Paying a shop or merchant",
    "friend": "Sending money to someone I know",
    "refund": "Receiving a refund",
    "investment": "An investment or scheme",
    "asked_to": "Someone asked me to pay",
}


@dataclass
class IntentAnalysis:
    supplied: bool
    intent: Optional[str] = None
    findings: list[VpaFinding] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.findings is None:
            self.findings = []

    @property
    def score(self) -> int:
        from backend.app.services.vpa import SEVERITY_WEIGHT
        return min(100, sum(SEVERITY_WEIGHT[f.severity] for f in self.findings))

    def as_dict(self) -> dict[str, Any]:
        return {
            "supplied": self.supplied,
            "intent": self.intent,
            "label": INTENTS.get(self.intent or "", None),
            "score": self.score,
            "findings": [
                {"code": f.code, "severity": f.severity, "message": f.message}
                for f in self.findings
            ],
        }


def analyse_intent(
    intent: Optional[str],
    *,
    merchant_code: Optional[str] = None,
    is_phone_payee: bool = False,
    established: bool = False,
    payee_name: Optional[str] = None,
) -> IntentAnalysis:
    """Contradictions between the stated purpose and the actual payee.

    `merchant_code` is the MCC carried by a genuine merchant QR. It is the
    honest way to ask "is this a business?" - the PSP handle (@okaxis, @ybl)
    says which bank issued the address and nothing at all about whether the
    holder is a shop or a person, which an earlier version of this got wrong.
    """
    if not intent:
        return IntentAnalysis(supplied=False)

    intent = intent.strip().lower()
    if intent not in INTENTS:
        return IntentAnalysis(supplied=False)

    findings: list[VpaFinding] = []

    # A genuine merchant QR carries a category code. No code, no history, and
    # a phone-number payee are each a reason to doubt "this is a business".
    unbusinesslike = is_phone_payee or (not merchant_code and not established)

    if intent == "bill" and unbusinesslike:
        who = "a phone number" if is_phone_payee else "an address with no merchant details"
        findings.append(VpaFinding(
            "intent_payee_mismatch", "high",
            f"You said this is a bill, but the money would go to {who}. Utilities and "
            f"billers are paid through registered merchant addresses, never a personal one."
        ))
    elif intent == "shop" and unbusinesslike:
        # Deliberately softer: plenty of small shops really do use a personal
        # UPI ID, so this is a question rather than an accusation.
        findings.append(VpaFinding(
            "intent_payee_mismatch", "warn",
            "You said this is a shop, but this address carries no merchant details and "
            "has no history here. Small shops often do use a personal UPI ID - check the "
            "name shown matches the shop."
        ))

    if intent == "refund":
        # The single most reliable rule in this entire system.
        findings.append(VpaFinding(
            "paying_for_a_refund", "critical",
            "A refund is money coming TO you. Nobody legitimate needs you to send "
            "a payment in order to receive one. This is how refund scams work."
        ))

    if intent == "investment" and not established:
        findings.append(VpaFinding(
            "investment_to_stranger", "high",
            "Investments paid directly to an individual UPI address, rather than to "
            "a regulated intermediary, are not recoverable if this goes wrong."
        ))

    if intent == "asked_to":
        findings.append(VpaFinding(
            "instructed_payment", "high",
            "You are paying because someone asked you to. That is the setup for "
            "almost every UPI scam - check who asked, on a number you already had."
        ))

    return IntentAnalysis(supplied=True, intent=intent, findings=findings)
