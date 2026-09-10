"""Tests for the coercion-context stream.

The tests that matter most here are the HARD NEGATIVES: genuine bank and
merchant messages that use urgency, authority and fear legitimately. A
detector that passes the scam cases and fails these is worse than nothing,
because it fires on real bank alerts and teaches people to dismiss the
warning.
"""

from __future__ import annotations

import pytest

from backend.app.services.coercion import (
    STRONG_PATTERNS,
    WEAK_PATTERNS,
    analyse_message,
    extract_features,
)
from backend.app.services.intent import analyse_intent
from backend.app.services.payee_check import _agreement_bonus, check_payee


# ── Pattern extraction ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,code", [
    ("Your account will be blocked today", "fear"),
    ("Please pay immediately", "urgency"),
    ("This is officer from cyber cell", "authority"),
    ("Do not tell anyone about this", "secrecy"),
    ("Install AnyDesk so I can help you", "remote_control"),
    ("Send Rs 1 for verification", "pay_request"),
    ("Pay a processing fee to continue", "verify_payment"),
    ("You have won a prize", "lure"),
    ("Call this number 9876543210", "contact_offline"),
    ("Share the OTP you received", "credential_request"),
    ("Aapka account band ho jayega, turant paise bhejo", "fear"),
])
def test_pattern_fires(text, code):
    assert extract_features(text)[code] == 1


def test_empty_message_is_not_evidence_of_safety():
    result = analyse_message(None)
    assert result.supplied is False
    assert result.score == 0
    assert result.findings == []


def test_devanagari_is_reported_as_uncovered_rather_than_clean():
    result = analyse_message("आपका खाता बंद हो जाएगा, तुरंत पैसे भेजो")
    assert result.language_note is not None
    assert "do not cover" in result.language_note


# ── Hard negatives: the whole point ──────────────────────────────────────────

HARD_NEGATIVES = [
    "Dear Customer, your HDFC Bank account XX4471 has been debited by Rs 2,300 on 04-03-2026. "
    "If this was not you, report immediately on the number printed on your card.",
    "Urgent: Your SBI debit card ending 8842 will be blocked for international use from "
    "12-04-2026 unless you enable it in the app.",
    "Your electricity bill of Rs 1,450 is due on 09-03-2026. Pay through the official portal "
    "to avoid disconnection.",
    "Urgent reminder: your loan EMI of Rs 4,500 is overdue. Please clear the outstanding "
    "immediately to avoid legal action and reporting to the credit bureau.",
    "Your loan application is approved. A one time processing fee of Rs 999 will be deducted "
    "from the disbursed amount as per the sanction letter.",
    "For any issue with this transaction, call our helpline number 18001234 between 9 AM and "
    "6 PM. We will never ask for your OTP, PIN or CVV.",
]


@pytest.mark.parametrize("text", HARD_NEGATIVES)
def test_genuine_bank_messages_do_not_reach_the_warning_threshold(text):
    """These all contain urgency, authority or fear - legitimately.

    If this test fails, the detector has learned to key on the alarm words that
    real banks use, and it would cry wolf on genuine alerts.
    """
    result = analyse_message(text)
    assert result.score < 50, (
        f"scored {result.score} on a genuine message: "
        f"{[f.code for f in result.findings]}"
    )


SCAMS = [
    "Dear customer, your SBI account will be blocked today as KYC is pending. Complete "
    "verification urgently by paying a refundable fee of Rs 10 to kyc-verify@ybl or call "
    "this number 9812345678.",
    "This is officer from cyber cell. A case will be filed against your account. Do not "
    "discuss this with anyone. Transfer Rs 45,000 to verify.now@okicici for verification of funds.",
    "Sir, I am from HDFC Bank. To restore your account please install AnyDesk and share your "
    "screen. Do not share this with family members.",
    "Aapka SBI account band ho jayega. Turant Rs 499 bhejo is UPI par kyc-verify@ybl. "
    "Kisi ko mat batao.",
]


@pytest.mark.parametrize("text", SCAMS)
def test_scam_messages_are_flagged(text):
    assert analyse_message(text).score >= 50


def test_urgency_alone_is_not_enough():
    """The single most important behaviour of this model.

    'Urgent' is in every second bank SMS. If urgency alone crossed the
    threshold, the feature would be unusable in practice.
    """
    assert analyse_message("Urgent: please respond immediately.").score < 50


def test_the_model_learned_authority_is_weak_evidence():
    """A message claiming to be from a bank, and nothing else, proves nothing."""
    assert analyse_message("This is a message from your bank.").score < 50


# ── Stated intent ─────────────────────────────────────────────────────────────

def test_paying_to_receive_a_refund_is_always_critical():
    result = analyse_intent("refund")
    assert any(f.severity == "critical" for f in result.findings)


def test_being_asked_to_pay_is_never_neutral():
    result = analyse_intent("asked_to")
    assert result.findings, "the payer reporting they were instructed must count for something"


def test_a_bill_paid_to_a_phone_number_is_a_contradiction():
    result = analyse_intent("bill", is_phone_payee=True)
    assert any(f.code == "intent_payee_mismatch" for f in result.findings)


def test_a_shop_without_merchant_details_is_a_question_not_an_accusation():
    """Small shops really do use personal UPI IDs - this must stay soft."""
    result = analyse_intent("shop", merchant_code=None, established=False)
    codes = {f.code: f.severity for f in result.findings}
    assert codes.get("intent_payee_mismatch") == "warn"


def test_a_real_merchant_qr_does_not_contradict_a_shop_payment():
    assert analyse_intent("shop", merchant_code="5411").findings == []


def test_unknown_intent_is_ignored_rather_than_guessed():
    assert analyse_intent("something-else").supplied is False


# ── Fusion ────────────────────────────────────────────────────────────────────

def test_agreement_counts_families_not_findings():
    """Four scam patterns in one message are still one family, not four."""
    bonus, agreeing = _agreement_bonus({"message_pressure": 90, "payee_history": 5})
    assert agreeing == ["message_pressure"] and bonus == 0

    bonus, agreeing = _agreement_bonus({"message_pressure": 90, "payee_history": 40})
    assert len(agreeing) == 2 and bonus > 0


def test_a_clean_payment_stays_clean_when_context_is_supplied():
    result = check_payee(
        "ramesh@okaxis",
        amount=500,
        intent="friend",
        message="Hey, I have sent you Rs 500 for dinner yesterday. Check once.",
    )
    assert result["decision"] == "APPROVE"


def test_context_is_optional_and_absence_is_not_safety():
    """Every existing caller must keep working, unchanged."""
    without = check_payee("ramesh@okaxis", amount=500)
    assert without["intent"]["supplied"] is False
    assert without["message_pressure"]["supplied"] is False
    assert without["decision"] in {"APPROVE", "WARN", "STEP_UP", "BLOCK"}


def test_agreeing_streams_reach_block_where_no_single_stream_would():
    """The actual contribution of this feature.

    The payee is unremarkable and the amount is ordinary, so neither the
    address nor the history stream would stop this on its own. The stated
    purpose contradicts the payee and the message shows coercion - and the
    combination is what produces the verdict.
    """
    result = check_payee(
        "9812345678@upi",
        amount=2000,
        intent="bill",
        message=(
            "Your electricity connection will be disconnected tonight. Pay immediately "
            "to 9812345678@upi or call this number 9876501234. Do not discuss this."
        ),
    )
    assert result["decision"] == "BLOCK"
    assert len(result["agreement"]["families"]) >= 2
    assert any(f["code"] == "streams_agree" for f in result["findings"])


def test_the_message_text_is_never_returned_to_the_caller():
    """The promise made on /payee/intents has to hold in the response too."""
    secret = "Do not tell anyone, pay Rs 5000 to kyc-verify@ybl immediately"
    result = check_payee("kyc-verify@ybl", amount=5000, intent="asked_to", message=secret)
    blob = repr(result)
    assert secret not in blob
    # Short quoted fragments are what make the finding readable; whole
    # sentences are not.
    for finding in result["message_pressure"]["findings"]:
        if finding["quote"]:
            assert len(finding["quote"]) <= 40


def test_every_pattern_has_a_severity_and_a_label():
    for pattern in WEAK_PATTERNS + STRONG_PATTERNS:
        assert pattern.label and pattern.terms
