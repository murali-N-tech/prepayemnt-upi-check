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

from backend.app.services.vpa import VpaFinding, total_weight

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
        return total_weight(self.findings)

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
        # Say so rather than returning the same shape as "nothing supplied".
        # A UI value drifting from this table would otherwise delete an
        # evidence family with no trace anywhere.
        return IntentAnalysis(
            supplied=False,
            findings=[VpaFinding(
                "intent_unrecognised", "info",
                f"'{intent}' is not a purpose this system knows, so the stated-purpose "
                f"check did not run."
            )],
        )

    findings: list[VpaFinding] = []

    # A genuine merchant QR carries a category code. No code, no history, and
    # a phone-number payee are each a reason to doubt "this is a business".
    unbusinesslike = is_phone_payee or (not merchant_code and not established)

    if intent == "bill" and unbusinesslike:
        who = "a phone number" if is_phone_payee else "an address with no merchant details"
        findings.append(VpaFinding(
            "intent_payee_mismatch", "high",
            f"You said this is a bill, but the money would go to {who}. Utilities and "
            f"billers are paid through registered merchant addresses, never a personal one.",
            # A bill "payable" to a phone number is a flat contradiction; one
            # payable to an address that merely carries no merchant details is
            # a strong suspicion. Both used to score an identical 35.
            weight=50 if is_phone_payee else 38,
        ))
    elif intent == "shop" and unbusinesslike:
        # Deliberately softer: plenty of small shops really do use a personal
        # UPI ID, so this is a question rather than an accusation.
        findings.append(VpaFinding(
            "intent_payee_mismatch", "warn",
            "You said this is a shop, but this address carries no merchant details and "
            "has no history here. Small shops often do use a personal UPI ID - check the "
            "name shown matches the shop.",
            # Deliberately near the bottom of the band: plenty of real shops
            # use a personal UPI ID, so this is a question, not a case.
            weight=18 if is_phone_payee else 12,
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
            "a regulated intermediary, are not recoverable if this goes wrong.",
            weight=52 if is_phone_payee else 44,
        ))

    if intent == "asked_to":
        findings.append(VpaFinding(
            "instructed_payment", "high",
            "You are paying because someone asked you to. That is the setup for "
            "almost every UPI scam - check who asked, on a number you already had.",
            # The payer has told us the premise of nearly every UPI scam
            # applies to this payment. Weighted high within the band, but not
            # at the top: being asked to pay is also how ordinary life works.
            weight=44,
        ))

    return IntentAnalysis(supplied=True, intent=intent, findings=findings)
