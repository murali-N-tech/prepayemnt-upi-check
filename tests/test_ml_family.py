"""The classifier as one evidence family among eleven.

It used to sit outside the assembly: /payee/check ran the payee-side families
through check_payee, ran the payer-side rules separately, and reconciled the
two with one if-statement. The combination rule never saw the model's reading,
so a payment the model scored well above its threshold could still come back
APPROVE if no deterministic family happened to notice it.

What these tests hold in place is narrower than "the model works". It is:

    an unavailable family scores null and changes nothing
    a missing payer profile disables the model rather than inventing one
    a missing PAYEE history does NOT disable it - that case was trained for
    the model contributes score but casts no agreement vote
    a hard block outranks the model in both directions
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.app.services.evidence import Evidence, Family, NON_VOTING, agreement_bonus
from backend.app.services.payee_check import (
    BLOCK_AT,
    ML_SOLO_CEILING,
    NON_VOTING_FAMILIES,
    STEP_UP_AT,
    _ml_evidence,
    check_payee,
)


def _ev(**scores):
    return [
        Evidence(family=Family(name), available=True, score=score, severity="warn")
        for name, score in scores.items()
    ]

PROFILE = {
    "median_amount": 220.0,
    "avg_amount": 610.0,
    "max_amount": 18500.0,
    "most_active_hour": 19,
    "average_daily_transactions": 3.2,
    "transaction_count": 280,
}
ESTABLISHED_PAYEE = {"known": True, "age_days": 900, "distinct_payers": 60,
                     "repeat_payers": 52}
YOUNG_PAYEE = {"known": True, "age_days": 3, "distinct_payers": 42, "repeat_payers": 0}
NO_HISTORY = {}

NORMAL_VELOCITY = {"seconds_since_last_txn": 7200.0, "txns_last_hour": 0.0, "txns_today": 2.0}
BURST_VELOCITY = {"seconds_since_last_txn": 90.0, "txns_last_hour": 6.0, "txns_today": 9.0}


def ml(amount, timestamp, profile, reputation, seen_before=False, velocity=None):
    return _ml_evidence(amount, timestamp, profile, reputation, seen_before,
                        velocity or NORMAL_VELOCITY)


# ── Available ────────────────────────────────────────────────────────────────

def test_ml_available_reports_a_score_and_its_model():
    e = ml(4500, "2026-09-13T18:24:00", PROFILE, YOUNG_PAYEE, velocity=BURST_VELOCITY)
    assert e["available"] is True
    assert isinstance(e["score"], int) and 0 <= e["score"] <= ML_SOLO_CEILING
    assert e["severity"] in {"info", "warn", "high"}
    assert e["code"] == "ml_behavioural_risk"
    assert e["message"]
    assert 0.0 <= e["probability"] <= 1.0
    assert e["model"]["operating_point"] == e["threshold"]
    assert e["model"]["kind"]


def test_an_ordinary_payment_scores_near_nothing():
    e = ml(90, "2026-09-17T13:20:00", PROFILE, ESTABLISHED_PAYEE, seen_before=True)
    assert e["available"] is True
    assert e["score"] <= 6
    assert e["probability"] < e["threshold"]


# ── Unavailable ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("amount, profile, why", [
    (None, PROFILE, "no amount"),
    (0, PROFILE, "zero amount"),
    (5000, None, "no payer profile"),
    (5000, {}, "empty payer profile"),
])
def test_ml_unavailable_returns_null_not_zero(amount, profile, why):
    e = ml(amount, "2026-09-17T13:20:00", profile, ESTABLISHED_PAYEE)
    assert e["available"] is False, why
    assert e["score"] is None, "a null score, never 0 - 0 is a measurement"
    assert e["severity"] is None
    assert e["model"] is None
    assert e["message"], "an unavailable family must say why"


def test_missing_payer_features_disable_the_model_rather_than_imputing():
    """Without a profile the payer features would fall back to population
    constants, and a made-up payer produces a made-up probability. The family
    reports absence instead."""
    e = ml(95_000, "2026-09-14T03:47:00", None, YOUNG_PAYEE)
    assert e["available"] is False
    assert "history for this payer" in e["message"]


def test_missing_payee_history_does_not_disable_the_model():
    """The opposite case, and the reason the model was retrained.

    A quarter of the training rows carry no payee history at all, so NaN there
    is an input the model has learned a response to. Disabling the family
    would throw away the payer-side reading on exactly the payments where the
    payee is a stranger - which is most first payments, and every mule.
    """
    e = ml(18_000, "2026-09-15T11:32:00", PROFILE, NO_HISTORY)
    assert e["available"] is True
    assert e["payee_history_available"] is False
    assert "payee_age_days" in e["features_unavailable"]
    assert e["score"] is not None


# ── It must not be able to lower risk ────────────────────────────────────────

def test_an_unavailable_model_cannot_reduce_the_verdict():
    """The same payment, with and without a payer profile. Losing the model
    may leave less evidence, but it must never make the result look better."""
    args = dict(payload="hdfcbank.refund@yb1", payer_id="u1", amount=47_500.0)
    with_model = check_payee(**args, profile=PROFILE, history=pd.DataFrame(),
                             timestamp="2026-09-16T19:21:00")
    without = check_payee(**args, timestamp="2026-09-16T19:21:00")

    assert without["ml"]["available"] is False
    assert with_model["risk_score"] >= without["risk_score"]
    order = ["APPROVE", "WARN", "STEP_UP", "BLOCK"]
    assert order.index(with_model["decision"]) >= order.index(without["decision"])


def test_unavailable_families_are_absent_from_the_arithmetic():
    r = check_payee("stranger@ybl", payer_id="u1", amount=500.0)
    assert "ml_classifier" not in r["component_scores"]
    assert "payer_behaviour" not in r["component_scores"]
    assert r["evidence_available"]["ml_classifier"] is False
    assert "ml_classifier" in r["missing_evidence"]


# ── No double counting ───────────────────────────────────────────────────────

def test_the_model_corroborates_only_on_facts_of_its_own():
    """It re-reads what other families already reported.

    The classifier reads the payer's amount, hour and velocity - which is what
    the payer-behaviour rules read - and the payee's age, payer count and
    repeat ratio, which is what the reputation family reads. Blanket-silencing
    it was the first fix; fact-aware corroboration is the accurate one, so it
    is no longer in NON_VOTING. Facts it shares with another family collapse;
    a fact nothing else observes still counts.
    """
    assert Family.ML_CLASSIFIER not in NON_VOTING
    assert "ml_classifier" not in NON_VOTING_FAMILIES

    from backend.app.services.evidence import Fact

    def row(family, fact, score=40):
        return Evidence(family=Family(family), available=True, score=score,
                        severity="high", facts=frozenset({fact}))

    others = [row("payee_history", Fact.PAYEE_SHAPE),
              row("amount_context", Fact.AMOUNT_ABSOLUTE)]

    # Declaring a fact the reputation family already reported adds nothing.
    duplicate = others + [row("ml_classifier", Fact.PAYEE_SHAPE, 55)]
    assert agreement_bonus(duplicate)[0] == agreement_bonus(others)[0]

    # On its own, with no second stream, it earns no bonus however high.
    assert agreement_bonus([row("ml_classifier", Fact.VELOCITY_HOURLY, 66)])[0] == 0


def test_the_payer_family_does_still_corroborate():
    """It reads the payer's own record, which no other family reads."""
    from backend.app.services.evidence import Fact

    assert Family.PAYER_BEHAVIOUR not in NON_VOTING
    pair = [
        Evidence(family=Family.PAYER_BEHAVIOUR, available=True, score=40,
                 severity="high", facts=frozenset({Fact.AMOUNT_DEVIATION})),
        Evidence(family=Family.PAYEE_HISTORY, available=True, score=30,
                 severity="high", facts=frozenset({Fact.PAYEE_SHAPE})),
    ]
    bonus, agreeing = agreement_bonus(pair)
    assert bonus > 0 and set(agreeing) == {"amount_deviation", "payee_shape"}


# ── The model cannot outrank a hard block, in either direction ───────────────

def test_a_hard_block_stands_whatever_the_model_says():
    r = check_payee("not-a-vpa", payer_id="u1", amount=500.0,
                    profile=PROFILE, history=pd.DataFrame(),
                    timestamp="2026-09-17T13:00:00")
    assert r["decision"] == "BLOCK"
    assert any(f["code"] == "vpa_malformed" for f in r["findings"])


def test_the_model_alone_cannot_reach_block():
    """It can reach STEP_UP unaided and needs corroboration to block.

    Not a claim that the model is unreliable - it is calibrated and its Brier
    skill is reported. It is the family most exposed to input the training
    distribution never covered, and a block is the verdict a user can least
    easily work around. Corroborated by an independent family, the agreement
    bonus lifts it past the threshold as it should.
    """
    assert ML_SOLO_CEILING < BLOCK_AT
    assert ML_SOLO_CEILING >= STEP_UP_AT


# ── Evidence coverage ────────────────────────────────────────────────────────

def test_full_evidence_reports_every_family_available():
    r = check_payee("srilakshmi.canteen@ybl", payer_id="u1", amount=90.0,
                    profile=PROFILE, history=pd.DataFrame(),
                    timestamp="2026-09-17T13:20:00",
                    intent="paying for lunch", message="see you at 1")
    assert r["evidence_available"]["ml_classifier"] is True
    assert r["evidence_available"]["payer_behaviour"] is True
    assert r["evidence_available"]["stated_intent"] is True
    assert r["evidence_available"]["message_pressure"] is True


def test_partial_evidence_when_the_payer_is_known_and_the_payee_is_not():
    r = check_payee("brandnew@ybl", payer_id="u1", amount=2500.0,
                    profile=PROFILE, history=pd.DataFrame(),
                    timestamp="2026-09-17T13:20:00")
    assert r["evidence_available"]["payer_behaviour"] is True
    assert r["evidence_available"]["ml_classifier"] is True
    assert r["evidence_available"]["payee_history"] is True   # a row is consulted
    assert r["ml"]["payee_history_available"] is False        # and it holds nothing


def test_minimal_evidence_when_neither_party_is_known():
    r = check_payee("brandnew@ybl", amount=2500.0)
    assert r["evidence_available"]["payer_behaviour"] is False
    assert r["evidence_available"]["ml_classifier"] is False
    assert set(r["missing_evidence"]) >= {"ml_classifier", "payer_behaviour"}
    assert 0 <= r["risk_score"] <= 99


# ── One assembly path ────────────────────────────────────────────────────────

def test_check_payee_is_the_only_thing_that_produces_a_verdict():
    r = check_payee("stranger@ybl", payer_id="u1", amount=1000.0,
                    profile=PROFILE, history=pd.DataFrame(),
                    timestamp="2026-09-17T13:20:00")
    assert r["decision"] in {"APPROVE", "WARN", "STEP_UP", "BLOCK"}
    # The model's own reading is reported inside the result, not beside it.
    assert "ml" in r and "probability" in r["ml"]
    # And no second vocabulary reaches the surface.
    assert "risk_level" not in r
    assert r["payer_behaviour"].get("detail", {}).get("risk_level") in {None, "LOW", "MEDIUM", "HIGH"}
