"""Corroboration counts observations, not modules.

The agreement bonus is worth a lot because independent streams rarely err
together. Counting FAMILIES made that easy to fake. The overlap audit found
the classifier and the payer rules sharing four inputs outright - the same
`hour < 6 or hour >= 22` predicate over the same timestamp, the same
distance-from-usual-hour expression, the same today-against-daily-average
ratio, and three separate routes to "has this payer paid this payee before" -
while the classifier's payee features are the very numbers the reputation
family scores. Two modules reading one clock is not two streams agreeing, and
the system was paying a corroboration bonus for having looked twice.

So families declare the FACTS their score rests on, and the bonus is bounded
by both quantities: it cannot exceed the number of distinct facts, and it
cannot exceed the number of independent families. Whichever is smaller wins.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.app.services.evidence import (
    AGREEMENT_BONUS,
    AGREEMENT_THRESHOLD,
    NON_VOTING,
    Evidence,
    Fact,
    Family,
    agreement_bonus,
    corroborating_facts,
)
from backend.app.services.payee_check import check_payee
from backend.app.services.merchant import merchant_key

FLAG = AGREEMENT_THRESHOLD + 10


def ev(family, facts, score=FLAG, available=True):
    if not available:
        return Evidence(family=family, available=False, unavailable_because="no data")
    return Evidence(family=family, available=True, score=score, severity="high",
                    code=f"{family.value}_x", facts=frozenset(facts))


# ── 1-4. Shared facts collapse ───────────────────────────────────────────────

def test_the_same_fact_from_two_families_is_one_corroboration():
    two = [ev(Family.PAYER_BEHAVIOUR, {Fact.HOUR_ANOMALY}),
           ev(Family.ML_CLASSIFIER, {Fact.HOUR_ANOMALY})]
    facts, sources = corroborating_facts(two)
    assert facts == [Fact.HOUR_ANOMALY]
    assert sources["hour_anomaly"] == ["ml_classifier", "payer_behaviour"]
    assert agreement_bonus(two)[0] == 0, "one observation, whoever reports it"


def test_the_same_fact_from_three_families_is_still_one_corroboration():
    three = [ev(Family.PAYER_BEHAVIOUR, {Fact.PAYEE_SHAPE}),
             ev(Family.ML_CLASSIFIER, {Fact.PAYEE_SHAPE}),
             ev(Family.PAYEE_HISTORY, {Fact.PAYEE_SHAPE})]
    facts, sources = corroborating_facts(three)
    assert facts == [Fact.PAYEE_SHAPE]
    assert len(sources["payee_shape"]) == 3
    assert agreement_bonus(three)[0] == 0


def test_different_facts_from_two_families_corroborate():
    two = [ev(Family.PAYEE_HISTORY, {Fact.PAYEE_SHAPE}),
           ev(Family.MESSAGE_PRESSURE, {Fact.MESSAGE_COERCION})]
    bonus, facts = agreement_bonus(two)
    assert bonus == AGREEMENT_BONUS[2]
    assert set(facts) == {"payee_shape", "message_coercion"}


def test_ml_payee_shape_plus_reputation_payee_shape_is_not_agreement():
    """The case the audit was about. The classifier's payee_age_days,
    payee_distinct_payers and payee_repeat_ratio ARE the reputation family's
    numbers. Reading them through a model does not make them a second
    observation of the world."""
    pair = [ev(Family.PAYEE_HISTORY, {Fact.PAYEE_SHAPE}, score=92),
            ev(Family.ML_CLASSIFIER, {Fact.PAYEE_SHAPE}, score=63)]
    assert agreement_bonus(pair)[0] == 0


# ── 5. A genuinely independent fact does corroborate ─────────────────────────

def test_hourly_velocity_corroborates_because_nothing_else_observes_it():
    """The payer rules count payments per DAY; the model also sees the last
    hour. A burst inside the hour is a materially different signal, so it is
    a different fact and is allowed to count."""
    pair = [ev(Family.PAYER_BEHAVIOUR, {Fact.VELOCITY_DAILY, Fact.AMOUNT_DEVIATION}),
            ev(Family.ML_CLASSIFIER, {Fact.VELOCITY_HOURLY})]
    bonus, facts = agreement_bonus(pair)
    assert bonus == AGREEMENT_BONUS[2]
    assert "velocity_hourly" in facts and "velocity_daily" in facts


# ── 6-7. What never contributes ──────────────────────────────────────────────

def test_unavailable_evidence_contributes_no_facts():
    assert corroborating_facts([ev(Family.PAYEE_HISTORY, set(), available=False)])[0] == []


def test_an_unavailable_family_cannot_declare_facts_at_all():
    with pytest.raises(ValueError, match="observed nothing"):
        Evidence(family=Family.PAYEE_HISTORY, available=False,
                 facts=frozenset({Fact.PAYEE_SHAPE}))


def test_a_non_voting_family_contributes_no_facts():
    """The mechanism is retained even though the classifier no longer needs
    it: a family whose score is a re-derivation of others, with no fact of its
    own, still belongs in NON_VOTING."""
    import backend.app.services.evidence as mod

    original = mod.NON_VOTING
    mod.NON_VOTING = frozenset({Family.MESSAGE_PRESSURE})
    try:
        pair = [ev(Family.PAYEE_HISTORY, {Fact.PAYEE_SHAPE}),
                ev(Family.MESSAGE_PRESSURE, {Fact.MESSAGE_COERCION})]
        assert corroborating_facts(pair)[0] == [Fact.PAYEE_SHAPE]
        assert agreement_bonus(pair)[0] == 0
    finally:
        mod.NON_VOTING = original


def test_the_classifier_is_no_longer_silenced_outright():
    assert Family.ML_CLASSIFIER not in NON_VOTING


def test_a_fact_below_the_participation_threshold_does_not_count():
    """A family murmuring at 6 is not evidence that corroborates anything,
    whatever it happened to read to get there."""
    pair = [ev(Family.PAYEE_HISTORY, {Fact.PAYEE_SHAPE}),
            ev(Family.MESSAGE_PRESSURE, {Fact.MESSAGE_COERCION}, score=AGREEMENT_THRESHOLD - 1)]
    assert corroborating_facts(pair)[0] == [Fact.PAYEE_SHAPE]
    assert agreement_bonus(pair)[0] == 0


# ── 13-15. Shape of the declarations ─────────────────────────────────────────

def test_many_families_sharing_one_fact_stay_one_corroboration():
    many = [ev(f, {Fact.AMOUNT_DEVIATION}) for f in
            (Family.PAYER_BEHAVIOUR, Family.ML_CLASSIFIER, Family.AMOUNT_CONTEXT,
             Family.PAYEE_HISTORY)]
    assert agreement_bonus(many)[0] == 0


def test_one_family_with_several_facts_is_still_one_opinion():
    """The regression that arrived the first time this was built without the
    family gate: the payer rules fire on the amount and the hour constantly,
    and counting that as two agreeing streams turned an ordinary monthly rent
    payment into a WARN."""
    alone = [ev(Family.PAYER_BEHAVIOUR,
                {Fact.AMOUNT_DEVIATION, Fact.HOUR_ANOMALY, Fact.VELOCITY_DAILY})]
    facts, _ = corroborating_facts(alone)
    assert len(facts) == 3
    assert agreement_bonus(alone)[0] == 0, "three observations, one stream"


def test_duplicate_tags_inside_one_family_collapse():
    e = Evidence(family=Family.PAYER_BEHAVIOUR, available=True, score=FLAG,
                 facts=[Fact.HOUR_ANOMALY, Fact.HOUR_ANOMALY, Fact.HOUR_ANOMALY])
    assert e.facts == frozenset({Fact.HOUR_ANOMALY})


def test_fact_tags_must_come_from_the_enum():
    """Guards against "payee_shape", "payee-shape" and "payee_history_shape"
    becoming three concepts."""
    with pytest.raises(ValueError, match="use the Fact enum"):
        Evidence(family=Family.PAYEE_HISTORY, available=True, score=FLAG,
                 facts=frozenset({"payee-shape"}))


def test_corroboration_never_exceeds_the_number_of_streams():
    pair = [ev(Family.PAYER_BEHAVIOUR, {Fact.AMOUNT_DEVIATION, Fact.HOUR_ANOMALY,
                                        Fact.VELOCITY_DAILY, Fact.PAYER_RELIABILITY}),
            ev(Family.PAYEE_HISTORY, {Fact.PAYEE_SHAPE})]
    assert agreement_bonus(pair)[0] == AGREEMENT_BONUS[2], "five facts, two streams"


# ── 8-10, 12. Behaviour preserved ────────────────────────────────────────────

PROFILE = {
    "median_amount": 220.0, "avg_amount": 610.0, "max_amount": 18500.0,
    "most_active_hour": 10, "average_daily_transactions": 3.2,
    "transaction_count": 280,
}


def test_hard_blocks_are_unchanged():
    for payload in ("not-a-vpa", ""):
        r = check_payee(payload or " ", payer_id="u1", amount=500.0,
                        profile=PROFILE, history=pd.DataFrame(),
                        timestamp="2026-09-17T13:00:00")
        assert r["verdict"] == "BLOCK"


def test_an_amount_over_the_rail_limit_still_blocks():
    r = check_payee("stranger@ybl", payer_id="u1", amount=150_000.0,
                    profile=PROFILE, history=pd.DataFrame(),
                    timestamp="2026-09-17T13:00:00")
    assert r["verdict"] == "BLOCK"
    assert any(f["code"] == "amount_over_upi_limit" for f in r["findings"])


def test_the_false_positive_probe_stays_approved():
    """A large but genuine payment to a payee the payer knows. Both
    behavioural families read the same amount ratio, so both can flag on one
    fact - and one fact from one stream must not become corroboration."""
    landlord = "ramanarao.k@oksbi"
    profile = dict(PROFILE,
                   known_upi_ids=[landlord],
                   known_merchant_keys=[merchant_key("K RAMANA RAO", landlord),
                                        merchant_key("", landlord)])
    r = check_payee(landlord, payer_id="u1", amount=8_000.0, profile=profile,
                    history=pd.DataFrame(), timestamp="2026-09-17T10:15:00")
    assert r["verdict"] == "APPROVE"
    assert r["agreement"]["bonus"] == 0


def test_the_response_reports_which_families_observed_each_fact():
    r = check_payee("hdfcbank.refund@yb1", payer_id="u1", amount=47_500.0,
                    profile=PROFILE, history=pd.DataFrame(),
                    timestamp="2026-09-16T19:21:00")
    agreement = r["agreement"]
    assert set(agreement) == {"facts", "bonus", "observed_by"}
    assert all(isinstance(v, list) for v in agreement["observed_by"].values())
    for row in r["evidence"]:
        assert isinstance(row["facts"], list)
        if not row["available"]:
            assert row["facts"] == []
