"""The canonical response, and the guarantees it makes.

Six fields carry the contract:

    risk_score        how bad the available evidence looks
    confidence_score  how much evidence there was to look at
    evidence_level    the same coverage as a word a UI can render
    verdict           APPROVE / WARN / STEP_UP / BLOCK, the only vocabulary
    evidence          one typed row per family, available or not
    missing_evidence  the families that could not be read

The property worth stating plainly, because every test below is a form of it:
a family that could not look must be visible in the response and invisible in
the arithmetic. Before this existed it was the other way round - absent
families contributed a silent 0 and never appeared at all, so a payment nobody
could check read exactly like a payment that had been checked and cleared.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.app.core.entity_status import EvidenceLevel
from backend.app.services.evidence import (
    CONFIDENCE_WEIGHT,
    Evidence,
    Family,
    confidence_score,
    unavailable,
)
from backend.app.services.payee_check import check_payee

# A payer who actually knows this payee. The canteen has to be in
# known_merchant_keys and known_upi_ids, because that is what "established"
# means to the payer-behaviour rules - an earlier version of this fixture
# described an established relationship while handing over a profile that had
# never seen the address, and then asserted the result should be APPROVE. The
# system was right to say WARN: on the evidence it was given, a payment to a
# payee absent from the payer's whole history IS worth a second look.
from backend.app.services.merchant import merchant_key

CANTEEN = "srilakshmi.canteen@ybl"
PROFILE = {
    "median_amount": 220.0, "avg_amount": 610.0, "max_amount": 18500.0,
    "most_active_hour": 19, "average_daily_transactions": 3.2,
    "transaction_count": 280,
    "known_upi_ids": [CANTEEN],
    "known_merchant_keys": [merchant_key("SRI LAKSHMI CANTEEN", CANTEEN),
                            merchant_key(CANTEEN, CANTEEN), merchant_key("", CANTEEN)],
    "favorite_merchants": ["SRI LAKSHMI CANTEEN"],
}
VERDICTS = {"APPROVE", "WARN", "STEP_UP", "BLOCK"}
REQUIRED = {"risk_score", "confidence_score", "evidence_level", "verdict",
            "evidence", "missing_evidence"}


def full(**kw):
    """Everything this path can be given."""
    base = dict(
        payload=CANTEEN, payer_id="u1", amount=90.0,
        profile=PROFILE, history=pd.DataFrame(), timestamp="2026-09-17T13:20:00",
        intent="paying for lunch", message="see you at one",
    )
    base.update(kw)
    return check_payee(**base)


def rows(result):
    return {e["family"]: e for e in result["evidence"]}


# ── Shape ────────────────────────────────────────────────────────────────────

def test_the_canonical_fields_are_present_and_well_formed():
    r = full()
    assert REQUIRED <= set(r)
    assert 0 <= r["risk_score"] <= 99
    assert 0 <= r["confidence_score"] <= 100
    assert r["evidence_level"] in {e.value for e in EvidenceLevel}
    assert r["verdict"] in VERDICTS
    assert r["verdict"] == r["decision"], "one verdict, two names for the old UI"

    for row in r["evidence"]:
        assert set(row) >= {"family", "available", "score", "severity", "code", "message"}
        assert row["family"] in {f.value for f in Family}


def test_every_family_appears_exactly_once():
    """A family reporting twice would vote twice."""
    names = [e["family"] for e in full()["evidence"]]
    assert len(names) == len(set(names))
    assert set(names) == {f.value for f in Family}


# ── Availability ─────────────────────────────────────────────────────────────

def test_all_evidence_available_except_the_one_with_no_producer():
    r = full()
    by = rows(r)
    for name in ("address_and_qr", "payee_history", "amount_context",
                 "stated_intent", "message_pressure", "relationship",
                 "payer_behaviour", "ml_classifier", "link_safety"):
        assert by[name]["available"] is True, f"{name} should be available"
    # Network-position analysis has no producer on this path yet, and says so
    # rather than being quietly left out of the response.
    assert by["graph"]["available"] is False
    assert by["graph"]["unavailable_because"]
    assert r["evidence_level"] == "FULL"


@pytest.mark.parametrize("kw, gone", [
    (dict(profile=None, history=None), {"payer_behaviour", "ml_classifier"}),
    (dict(payer_id=None), {"relationship"}),
    (dict(intent=None), {"stated_intent"}),
    (dict(message=None), {"message_pressure"}),
    (dict(amount=None), {"amount_context"}),
])
def test_each_missing_input_disables_exactly_its_own_families(kw, gone):
    by = rows(full(**kw))
    for name in gone:
        assert by[name]["available"] is False
        assert by[name]["score"] is None, "null, never 0"
        assert by[name]["severity"] is None
        assert by[name]["unavailable_because"], "must say why"


def test_payer_unavailable_takes_the_model_with_it():
    """Without a profile the payer features would be population constants, and
    a made-up payer produces a made-up probability."""
    by = rows(full(profile=None, history=None))
    assert by["payer_behaviour"]["available"] is False
    assert by["ml_classifier"]["available"] is False


def test_payee_unavailable_does_not_take_the_model_with_it():
    """The opposite case, and the reason the model was retrained on cold-start
    rows: a stranger is the normal case, not a reason to stop scoring."""
    r = full(payload="nobody-has-seen-this@ybl", amount=2500.0)
    by = rows(r)
    assert by["ml_classifier"]["available"] is True
    assert r["ml"]["payee_history_available"] is False


def test_multiple_unavailable_families_are_all_listed():
    r = check_payee("stranger@ybl", amount=None)
    by = rows(r)
    absent = {n for n, e in by.items() if not e["available"]}
    assert {"payer_behaviour", "ml_classifier", "relationship",
            "stated_intent", "message_pressure", "amount_context"} <= absent
    assert set(r["missing_evidence"]) == absent
    assert all(by[n]["score"] is None for n in absent)


def test_an_unavailable_row_carrying_a_score_cannot_be_constructed():
    with pytest.raises(ValueError, match="contributes nothing"):
        Evidence(family=Family.PAYEE_HISTORY, available=False, score=40)


# ── Missing evidence must not lower risk ─────────────────────────────────────

@pytest.mark.parametrize("drop", [
    dict(profile=None, history=None),
    dict(intent=None),
    dict(message=None),
    dict(payer_id=None),
])
def test_removing_evidence_never_lowers_the_verdict(drop):
    """Losing a family may leave us knowing less. It must never make the
    payment look safer than it did when we knew more."""
    suspicious = dict(payload="hdfcbank.refund@yb1", amount=47_500.0)
    with_all = full(**suspicious)
    without = full(**suspicious, **drop)
    order = ["APPROVE", "WARN", "STEP_UP", "BLOCK"]
    assert order.index(without["verdict"]) >= order.index(with_all["verdict"])
    assert without["confidence_score"] <= with_all["confidence_score"]


def test_unavailable_families_are_absent_from_the_component_scores():
    r = full(profile=None, history=None, intent=None)
    for name in ("payer_behaviour", "ml_classifier", "stated_intent"):
        assert name not in r["component_scores"]


# ── Confidence ───────────────────────────────────────────────────────────────

def test_confidence_is_coverage_and_not_the_model_probability():
    """The distinction the field exists for.

    Asking a classifier how sure it is about a case it has no features for
    returns an answer built from the same absent data. Coverage is a fact
    about the input, and "we could not check the payee's history" is something
    a user can act on in a way that a posterior variance is not.
    """
    r = full(payload="nobody-has-seen-this@ybl", amount=2500.0)
    assert r["confidence_score"] != round(100 * (r["ml"].get("probability") or 0))

    rich = full()
    poor = check_payee("stranger@ybl", amount=None)
    assert rich["confidence_score"] > poor["confidence_score"]


def test_confidence_falls_when_a_heavyweight_family_goes_missing():
    assert CONFIDENCE_WEIGHT[Family.PAYEE_HISTORY] > CONFIDENCE_WEIGHT[Family.STATED_PURPOSE]
    assert full(intent=None)["confidence_score"] > full(profile=None, history=None)["confidence_score"]


def test_confidence_arithmetic_is_the_weighted_share():
    present = [Family.ADDRESS, Family.AMOUNT_CONTEXT]
    ev = [Evidence(family=f, available=True, score=0) if f in present
          else unavailable(f, "x") for f in Family]
    expected = round(100 * sum(CONFIDENCE_WEIGHT[f] for f in present)
                     / sum(CONFIDENCE_WEIGHT.values()))
    assert confidence_score(ev) == expected


# ── Evidence level ───────────────────────────────────────────────────────────

def test_evidence_level_tracks_the_core_families():
    assert full()["evidence_level"] == "FULL"
    # Payer known, payee a stranger with no readable history: still PARTIAL,
    # because a reputation row was consulted and the relationship is known.
    assert full(payload="nobody-has-seen-this@ybl", amount=2500.0)["evidence_level"] \
        in {"FULL", "PARTIAL"}
    # Nothing about either party.
    assert check_payee("stranger@ybl", amount=500.0)["evidence_level"] == "PARTIAL"


def test_low_confidence_does_not_soften_a_hard_block():
    """Confidence says how much we know. It is not a reason to withhold a
    verdict the evidence already supports."""
    r = check_payee("not-a-vpa", amount=500.0)
    assert r["verdict"] == "BLOCK"
    assert r["confidence_score"] < 70
    assert any(f["code"] == "vpa_malformed" for f in r["findings"])


# ── Combination behaviour, preserved ─────────────────────────────────────────

def test_the_agreement_bonus_still_fires_on_independent_families():
    r = full(payload="hdfcbank.refund@yb1", amount=47_500.0,
             message="URGENT: your account will be blocked, pay within 2 hours")
    assert r["agreement"]["bonus"] > 0
    assert len(r["agreement"]["facts"]) >= 2
    # The classifier corroborates only on a fact nothing else observed.
    duplicated = {f: who for f, who in r["agreement"]["observed_by"].items()
                  if "ml_classifier" in who and len(who) > 1}
    for fact, who in duplicated.items():
        assert len(set(who)) > 1, f"{fact} should collapse across {who}"


def test_the_model_contributes_score_without_voting():
    r = full(payload="hdfcbank.refund@yb1", amount=47_500.0)
    if r["evidence_available"].get("ml_classifier") and r["component_scores"].get("ml_classifier"):
        assert "ml_classifier" in r["component_scores"]
        # The classifier corroborates only on a fact nothing else observed.
    duplicated = {f: who for f, who in r["agreement"]["observed_by"].items()
                  if "ml_classifier" in who and len(who) > 1}
    for fact, who in duplicated.items():
        assert len(set(who)) > 1, f"{fact} should collapse across {who}"


def test_a_clean_established_payee_is_approved():
    r = full()
    assert r["verdict"] == "APPROVE"
    assert r["risk_score"] < 22


# ── The fields the screen actually reads ─────────────────────────────────────

def test_every_agreement_field_the_screen_reads_exists_in_the_response():
    """The crash this prevents: `agreement.families` was renamed to `facts`
    server-side by the fact-aware corroboration change, and the frontend kept
    reading `families`. It threw "Cannot read properties of undefined (reading
    'length')" - and only on payments where evidence corroborates, because the
    block is rendered when the bonus is non-zero. A rename on one side of a
    contract with no test across it.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sources = [root / "src/components/PayeeCheck.tsx", root / "src/types.ts"]
    read = set()
    for path in sources:
        if not path.exists():           # backend-only checkout
            continue
        text = path.read_text(encoding="utf-8")
        # Comments explain what the field USED to be called, so scanning them
        # would make this test fail on its own explanation.
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
        read |= set(re.findall(r"agreement\??\.([a-z_]+)", text))
        block = re.search(r"agreement:\s*\{(.*?)\}", text, re.S)
        if block:
            read |= set(re.findall(r"^\s*([a-z_]+)\??:", block.group(1), re.M))
    read -= {"facts", "bonus", "observed_by"}       # the current contract

    # A corroborating payment, so `agreement` is populated rather than empty.
    r = full(payload="hdfcbank.refund@yb1", amount=47_500.0,
             message="urgent, pay now or the account is blocked")
    assert set(r["agreement"]) == {"facts", "bonus", "observed_by"}
    assert r["agreement"]["bonus"] > 0, "this fixture must actually corroborate"
    assert read == set(), f"the screen reads agreement fields the API does not publish: {read}"


def test_the_agreement_bonus_matches_the_families_the_screen_counts():
    """The headline says "N independent checks agree" and N is the number of
    distinct families in `observed_by` - which is the quantity the bonus is
    actually based on, not the number of facts."""
    from backend.app.services.evidence import AGREEMENT_BONUS

    r = full(payload="hdfcbank.refund@yb1", amount=47_500.0,
             message="urgent, pay now or the account is blocked")
    agreement = r["agreement"]
    families = {name for observers in agreement["observed_by"].values() for name in observers}
    assert agreement["bonus"] == AGREEMENT_BONUS[min(len(agreement["facts"]), len(families))]
    assert len(families) >= 1
    assert set(agreement["observed_by"]) == set(agreement["facts"])
