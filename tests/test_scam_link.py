"""Tests for the scam-link half of the title.

Same discipline as the coercion tests: the hard negatives are real addresses
that Indian banks, government departments and merchants actually use. A link
checker that flags onlinesbi.sbi is not a link checker, it is a nuisance.
"""

from __future__ import annotations

import pytest

from backend.app.services.payee_check import check_payee
from backend.app.services.scam_link import (
    analyse_links,
    analyse_url,
    brand_conflicts_with_payee,
    extract_urls,
    registrable_domain,
)


# ── Hard negatives: addresses that must never be flagged ─────────────────────

REAL_ADDRESSES = [
    "https://onlinesbi.sbi/login",
    "https://www.icicibank.com/personal-banking",
    "https://netbanking.hdfcbank.com/netbanking/",
    "https://www.axisbank.com/retail",
    "https://www.pnbindia.in",
    "https://irctc.co.in/nget/train-search",
    "https://www.incometax.gov.in/iec/foportal",
    "https://uidai.gov.in/my-aadhaar",
    "https://npci.org.in/what-we-do/upi",
    "https://www.paytm.com/recharge",
    "https://www.phonepe.com/business-solutions",
    "https://groww.in/stocks",
    "https://www.amazon.in/orders",
]


@pytest.mark.parametrize("url", REAL_ADDRESSES)
def test_real_addresses_are_not_flagged(url):
    verdict = analyse_url(url)
    loud = [f.code for f in verdict.findings if f.severity in {"warn", "high", "critical"}]
    assert not loud, f"{url} was flagged: {loud}"


# ── Scam structures ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,code", [
    ("http://192.168.4.10/kyc", "link_ip_host"),
    ("https://xn--paytm-9va.com/refund", "link_punycode"),
    ("https://icicibank.com@evil.tk/login", "link_credentials_in_url"),
    ("https://cdn.example.top/sbi-update.apk", "link_app_download"),
    ("http://0nlinesbi.com/verify", "link_brand_typosquat"),
    ("https://sbi.secure-login.xyz/net", "link_brand_in_subdomain"),
    ("https://sbi-kyc-verify.top/update", "link_brand_not_on_own_domain"),
    ("https://bit.ly/3xTz9k", "link_shortener"),
])
def test_scam_structures_are_caught(url, code):
    codes = {f.code for f in analyse_url(url).findings}
    assert code in codes, f"expected {code}, got {sorted(codes)}"


def test_homoglyph_folding_is_shared_with_the_vpa_checker():
    """0nlinesbi is to onlinesbi what okaxls is to okaxis - one mechanism."""
    assert analyse_url("http://0nlinesbi.com").features["brand_typosquat"] == 1


# ── Parsing ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host,expected", [
    ("www.icicibank.com", "icicibank.com"),
    ("netbanking.hdfcbank.com", "hdfcbank.com"),
    ("irctc.co.in", "irctc.co.in"),
    ("a.b.incometax.gov.in", "incometax.gov.in"),
    ("evil.tk", "evil.tk"),
])
def test_registrable_domain_understands_indian_suffixes(host, expected):
    assert registrable_domain(host) == expected


def test_urls_are_extracted_from_running_text():
    urls = extract_urls("Pay at https://sbi-verify.top/now or call 9876543210 today")
    assert urls == ["https://sbi-verify.top/now"]


def test_trailing_punctuation_is_not_part_of_the_url():
    assert extract_urls("go to sbi-verify.top.") == ["sbi-verify.top"]


def test_file_names_are_not_mistaken_for_domains():
    assert extract_urls("see statement.pdf and photo.jpg") == []


def test_no_message_means_no_links_rather_than_no_risk():
    analysis = analyse_links(None)
    assert analysis.found == 0 and analysis.score == 0


def test_the_worst_link_decides_rather_than_the_sum():
    """Two bad links are not twice as bad as one."""
    analysis = analyse_links("http://192.168.0.1/a and http://192.168.0.2/b")
    assert analysis.found == 2
    assert analysis.score == max(link.score for link in analysis.links)


# ── The cross-modal check ────────────────────────────────────────────────────

def test_a_brand_link_paying_an_unrelated_address_is_a_conflict():
    analysis = analyse_links("verify at https://sbi-kyc.top/update")
    conflict = brand_conflicts_with_payee(analysis, "rk4482@ybl")
    assert conflict is not None and conflict.severity == "high"


def test_a_brand_link_paying_that_brand_is_not_a_conflict():
    analysis = analyse_links("pay via https://sbi-kyc.top/update")
    assert brand_conflicts_with_payee(analysis, "sbi.collect@sbi") is None


def test_no_link_means_no_conflict_claim():
    assert brand_conflicts_with_payee(analyse_links("no links here"), "rk4482@ybl") is None


# ── Fusion ───────────────────────────────────────────────────────────────────

def test_a_link_pushes_a_payment_over_the_line_with_other_streams():
    result = check_payee(
        "rk4482@ybl",
        amount=1500,
        intent="bill",
        message=(
            "Your SBI account is blocked. Complete KYC at https://sbi-kyc-verify.top/update "
            "and pay Rs 10 to rk4482@ybl immediately."
        ),
    )
    assert result["decision"] == "BLOCK"
    # The corroborating entries are FACTS now, not family names: the link
    # family observes link_reputation.
    assert "link_reputation" in result["agreement"]["facts"]
    assert "link_safety" in result["agreement"]["observed_by"]["link_reputation"]
    assert result["links"]["found"] == 1


def test_an_ordinary_payment_with_a_real_link_stays_clean():
    result = check_payee(
        "ramesh@okaxis",
        amount=500,
        intent="friend",
        message="Booked the tickets on https://irctc.co.in/nget/train-search, sending your share.",
    )
    assert result["decision"] == "APPROVE"
    assert result["component_scores"]["link_safety"] == 0


def test_link_analysis_is_present_even_when_nothing_was_supplied():
    result = check_payee("ramesh@okaxis", amount=500)
    assert result["links"]["found"] == 0
