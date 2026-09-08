"""The pre-payment payee check: address analysis, QR parsing, reputation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.services import payee_reputation as pr
from backend.app.services import profile_store
from backend.app.services.payee_check import check_payee
from backend.app.services.upi_qr import parse_upi_target
from backend.app.services.vpa import analyse_vpa, canonical, looks_like_phone


# ── Address analysis ──────────────────────────────────────────────────────

@pytest.mark.parametrize("address", [
    "swiggy@ibl", "zomato@paytm", "irctc@paytm", "murali@okaxis",
    "rakesh9911@ibl", "chinthada.murali@oksbi", "9876543210@upi",
])
def test_real_addresses_are_not_flagged(address):
    """A legitimate merchant address must not score. swiggy@ibl really is
    Swiggy's address, so 'contains a brand name' cannot be a risk on its own."""
    assert analyse_vpa(address).score == 0


@pytest.mark.parametrize("address,expect", [
    ("sbi-refund@okaxis", "brand_lure"),
    ("hdfcbank-kyc@ptaxis", "brand_lure"),
    ("sbiverify123@paytm", "brand_lure"),
    ("icicl@okaxis", "brand_confusable"),
    ("name@okax1s", "handle_confusable"),
    ("name@okaxls", "handle_confusable"),
    ("notavpa", "vpa_malformed"),
])
def test_lookalike_addresses_are_caught(address, expect):
    codes = {f.code for f in analyse_vpa(address).findings}
    assert expect in codes, f"{address} -> {codes}"


def test_digit_substitution_is_folded():
    # '1' standing in for 'i' must not defeat the name check.
    assert canonical("sb1support") == canonical("sbisupport")
    assert "brand_lure" in {f.code for f in analyse_vpa("sb1support@ybl").findings}


def test_phone_numbers_are_recognised():
    assert looks_like_phone("9876543210") == "9876543210"
    assert looks_like_phone("+91 9876543210") == "9876543210"
    assert looks_like_phone("1234567890") is None      # Indian mobiles start 6-9
    assert looks_like_phone("swiggy@ibl") is None


# ── QR / deep-link parsing ────────────────────────────────────────────────

def test_deep_link_fields_are_extracted():
    qr = parse_upi_target("upi://pay?pa=shop@okaxis&pn=Chai%20Point&am=40.50&tn=Tea&cu=INR")
    assert qr.kind == "deep_link"
    assert qr.payee_vpa == "shop@okaxis"
    assert qr.payee_name == "Chai Point"
    assert qr.amount == 40.50 and qr.amount_locked
    assert qr.note == "Tea"


def test_a_non_upi_qr_is_rejected():
    qr = parse_upi_target("https://bit.ly/free-money")
    assert "not_a_payment_link" in {f.code for f in qr.all_findings}


def test_embedded_url_is_flagged():
    qr = parse_upi_target("upi://pay?pa=shop@okaxis&pn=Shop&url=http%3A%2F%2Fbit.ly%2Fx")
    assert "embedded_url" in {f.code for f in qr.all_findings}


def test_display_name_not_matching_the_address_is_flagged():
    """The signature of a sticker pasted over a shop's real QR."""
    qr = parse_upi_target("upi://pay?pa=rakesh9911@ybl&pn=Reliance%20Digital&am=48999")
    assert "name_mismatch" in {f.code for f in qr.all_findings}


def test_matching_display_name_is_not_flagged():
    qr = parse_upi_target("upi://pay?pa=chaipoint@okaxis&pn=Chai%20Point&am=40")
    assert "name_mismatch" not in {f.code for f in qr.all_findings}


# ── Reputation ────────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(profile_store, "DB_PATH", tmp_path / "rep.db")
    conn = pr.connect()
    yield conn
    conn.close()


def _at(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_an_unseen_payee_is_reported_as_unseen(store):
    rep = pr.assess_payee("brandnew@ybl", conn=store)
    assert rep.known is False
    assert "payee_unseen" in {f.code for f in rep.findings}


def test_distinct_payers_are_counted_not_payments(store):
    for i in range(3):
        pr.record_payment("shop@okaxis", "payer_a", 100, _at(10 - i), conn=store)
    pr.record_payment("shop@okaxis", "payer_b", 100, _at(5), conn=store)
    rep = pr.assess_payee("shop@okaxis", conn=store)
    assert rep.payment_count == 4
    assert rep.distinct_payers == 2
    assert rep.repeat_payers == 1


def test_collection_account_pattern_is_detected(store):
    """New account, many unrelated payers, nobody pays twice."""
    for i in range(20):
        pr.record_payment("mule@ybl", f"payer_{i}", 5000, _at(8 - i * 0.2), conn=store)
    rep = pr.assess_payee("mule@ybl", conn=store)
    assert "mule_pattern" in {f.code for f in rep.findings}
    assert rep.score >= 70


def test_an_established_merchant_is_reassuring_not_alarming(store):
    for i in range(60):
        pr.record_payment("chai@okhdfcbank", f"payer_{i % 12}", 40 + (i % 5) * 20,
                          _at(400 - i * 5), conn=store)
    rep = pr.assess_payee("chai@okhdfcbank", conn=store)
    codes = {f.code for f in rep.findings}
    assert "payee_established" in codes
    assert rep.score == 0


def test_reports_raise_the_score(store):
    pr.record_payment("dodgy@ybl", "payer_1", 1000, _at(5), conn=store)
    before = pr.assess_payee("dodgy@ybl", conn=store).score
    for i in range(3):
        pr.report_payee("dodgy@ybl", f"reporter_{i}", "scam")
    after = pr.assess_payee("dodgy@ybl", conn=store)
    assert after.reports == 3
    assert after.score > before


def test_the_same_person_reporting_twice_counts_once(store):
    pr.report_payee("dodgy2@ybl", "reporter_1", "scam")
    pr.report_payee("dodgy2@ybl", "reporter_1", "scam again")
    assert pr.assess_payee("dodgy2@ybl", conn=store).reports == 1


def test_a_blocked_payee_is_critical(store):
    pr.set_blocked("blocked@ybl", True)
    rep = pr.assess_payee("blocked@ybl", conn=store)
    assert rep.blocked is True
    assert "payee_blocked" in {f.code for f in rep.findings}


def test_payee_key_prefers_the_address_over_the_name(store):
    assert pr.payee_key("Shop@OkAxis", "Some Shop") == "shop@okaxis"
    assert pr.payee_key(None, "Chai Point") == "name:chai-point"
    assert pr.payee_key("", "") == ""


# ── End-to-end decisions ──────────────────────────────────────────────────

@pytest.mark.parametrize("payload,amount,expected", [
    ("upi://pay?pa=friend@okaxis&pn=Friend&am=250", None, "APPROVE"),
    ("sbi-refund@okaxis", 5000, "BLOCK"),
    ("https://bit.ly/claim", None, "BLOCK"),
    ("notavpa", None, "BLOCK"),
    ("upi://pay?pa=rakesh9911@ybl&pn=Reliance%20Digital&am=48999", None, "STEP_UP"),
])
def test_decisions(store, payload, amount, expected):
    assert check_payee(payload, payer_id="u1", amount=amount, conn=store)["decision"] == expected


def test_a_critical_finding_blocks_on_its_own(store):
    """One critical finding must be decisive; it should not need a second
    signal to cross the threshold."""
    result = check_payee("sbi-refund@okaxis", conn=store)
    assert any(f["severity"] == "critical" for f in result["findings"])
    assert result["decision"] == "BLOCK"


def test_large_amount_to_an_unknown_payee_escalates(store):
    small = check_payee("unknown@okaxis", amount=200, conn=store)
    large = check_payee("unknown@okaxis", amount=60000, conn=store)
    assert large["risk_score"] > small["risk_score"]
    assert large["component_scores"]["amount_context"] > 0
