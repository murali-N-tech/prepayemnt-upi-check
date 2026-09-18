"""How "unusual for this payer" is measured, and what happens when it cannot be.

Three places in the system compare a payment against an amount, and an audit
traced all three end to end because two of them disagree about which statistic
to use:

    the model            amount / median_amount   (learned, trained on medians)
    the payer rules      amount / avg_amount      (a fixed 15x/8x/3x ladder)
    amount_context       amount against the UPI cap and LARGE_AMOUNT

The disagreement is deliberate and the tests below pin it in place, because
"fixing" it the obvious way makes the system worse: on a payer whose spend is
bimodal - daily payments around Rs 220 and rent at Rs 18,500 - the mean is
1,523 and the median 222, so judged against the median the monthly rent is 83x
and lands in the same top band as outright fraud at 416x. The ladder loses its
resolution exactly where it needs it, and an ordinary recurring payment becomes
a WARN every month. The model does not have that problem because it learned the
relationship rather than being handed a threshold.

What the audit did change is the cold start. A payer with one prior payment of
Rs 10 has a median of Rs 10, and an ordinary Rs 5,000 transfer then reads as
500x their norm - not a measurement, one data point being asked to describe a
distribution. Below MIN_PAYMENTS_FOR_AMOUNT_BASELINE the amount comparison
reports itself unavailable instead of producing arithmetic.

The last group is the one that matters most: the same underlying observation -
this payment is large for this payer - must be counted ONCE however many
modules notice it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.services.evidence import AGREEMENT_BONUS, Fact, Family
from backend.app.services.payee_check import _ml_evidence, check_payee
from backend.app.services.personalized_risk_service import evaluate_personalized_risk
from backend.app.services.statement_parser import generate_behavior_profile
from backend.ml.dataset import FEATURES, LABEL, generate
from backend.ml.features import (
    MIN_PAYMENTS_FOR_AMOUNT_BASELINE,
    POPULATION_MEDIAN_AMOUNT,
    amount_baseline_is_measurable,
    build_vector,
    payer_baseline_amount,
)

TS = "2026-09-17T13:20:00"
NIGHT = "2026-09-17T02:30:00"
NORMAL_VELOCITY = {"seconds_since_last_txn": 7200.0, "txns_last_hour": 0.0, "txns_today": 2.0}
BURST_VELOCITY = {"seconds_since_last_txn": 90.0, "txns_last_hour": 6.0, "txns_today": 9.0}
ESTABLISHED_PAYEE = {"known": True, "age_days": 900, "distinct_payers": 60,
                     "repeat_payers": 52}
EMPTY_HISTORY = pd.DataFrame()


def profile(n_payments=40, *, avg=610.0, median=220.0, maximum=18500.0, **extra):
    """A payer profile with the fields the amount comparisons actually read."""
    p = {
        "transaction_count": n_payments,
        "debit_count": n_payments,
        "avg_amount": avg,
        "median_amount": median,
        "max_amount": maximum,
        "most_active_hour": 19,
        "average_daily_transactions": 3.2,
    }
    p.update(extra)
    return p


def payer(p, amount, timestamp=TS, merchant="SRI LAKSHMI CANTEEN", upi_id="canteen@ybl"):
    return evaluate_personalized_risk(
        profile=p, history=EMPTY_HISTORY, amount=amount,
        merchant=merchant, timestamp=timestamp, upi_id=upi_id,
    )


def ml(p, amount, timestamp=TS, reputation=None, velocity=None, seen_before=True):
    return _ml_evidence(amount, timestamp, p, reputation or ESTABLISHED_PAYEE,
                        seen_before, velocity or NORMAL_VELOCITY)


def amount_facts(result):
    return [r for r in result["reasons"] if "average" in r or "usual pattern" in r
            or "previously seen" in r]


# ── 1. A payer the system has never seen ─────────────────────────────────────

def test_a_new_payer_has_no_amount_baseline_at_all():
    assert payer_baseline_amount(None) == 0.0
    assert payer_baseline_amount({}) == 0.0
    assert amount_baseline_is_measurable(None) is False
    assert amount_baseline_is_measurable({}) is False


def test_a_new_payer_disables_the_model_rather_than_inventing_a_baseline():
    e = ml(None, 48_000)
    assert e["available"] is False
    assert e["score"] is None
    assert "history" in e["message"]


def test_a_new_payer_gets_a_population_denominator_marked_as_not_measured():
    """The ratio still has to be a number for the feature vector. What must not
    happen is the vector claiming it measured this payer."""
    v = build_vector(amount=600.0, timestamp=TS, profile={}, reputation={},
                     payer_seen_payee_before=None, **NORMAL_VELOCITY)
    assert v.values["amount_over_user_avg"] == 600.0 / POPULATION_MEDIAN_AMOUNT
    assert v.available["amount_over_user_avg"] is False
    assert "amount_over_user_avg" in v.missing()


def test_a_new_payer_scores_a_baseline_not_an_amount_multiple():
    r = payer(None, 48_000)
    assert r["profile_available"] is False
    assert r["comparison"] == {}
    assert amount_facts(r) == []


# ── 2. One prior payment: the baseline IS the outlier ────────────────────────

def test_one_prior_payment_is_not_a_baseline():
    thin = profile(1, avg=10.0, median=10.0, maximum=10.0)
    assert payer_baseline_amount(thin) == 10.0, "the figure exists"
    assert amount_baseline_is_measurable(thin) is False, "it just does not mean anything"


def test_one_prior_payment_does_not_make_an_ordinary_transfer_500x_suspicious():
    """Before the audit: median Rs 10, so Rs 5,000 read as 500x their norm and
    the payer rules scored it 87 on the amount alone."""
    thin = profile(1, avg=10.0, median=10.0, maximum=10.0)
    r = payer(thin, 5_000)
    assert amount_facts(r) == []
    assert "amount_multiple" not in r["comparison"]
    assert Fact.AMOUNT_DEVIATION.value not in r["facts"]
    assert r["risk_score"] < 45, "no step-up from arithmetic on one data point"


def test_one_prior_payment_reports_the_model_unavailable_and_says_why():
    thin = profile(1, avg=10.0, median=10.0, maximum=10.0)
    e = ml(thin, 5_000)
    assert e["available"] is False and e["score"] is None
    assert str(MIN_PAYMENTS_FOR_AMOUNT_BASELINE) in e["message"]
    assert "baseline" in e["message"]


def test_the_baseline_becomes_measurable_exactly_at_the_documented_count():
    below = profile(MIN_PAYMENTS_FOR_AMOUNT_BASELINE - 1)
    at = profile(MIN_PAYMENTS_FOR_AMOUNT_BASELINE)
    assert amount_baseline_is_measurable(below) is False
    assert amount_baseline_is_measurable(at) is True


def test_credits_do_not_count_towards_a_spending_baseline():
    """Forty credits and one debit describes someone receiving money."""
    receiving = profile(1, avg=10.0, median=10.0, maximum=10.0)
    receiving["transaction_count"] = 41
    receiving["debit_count"] = 1
    assert amount_baseline_is_measurable(receiving) is False


# ── 3. Several normal payments ───────────────────────────────────────────────

def test_a_payer_with_a_real_history_is_compared_against_it():
    p = profile(40)
    assert amount_baseline_is_measurable(p) is True
    r = payer(p, 240.0)
    assert r["comparison"]["average_amount"] == 610.0
    assert pytest.approx(r["comparison"]["amount_multiple"], abs=0.01) == 240.0 / 610.0
    assert amount_facts(r) == [], "an ordinary payment is not an amount finding"


def test_an_ordinary_payment_from_a_real_history_scores_near_nothing():
    e = ml(profile(40), 240.0)
    assert e["available"] is True
    assert e["score"] <= 6


# ── 4. An extreme outlier ────────────────────────────────────────────────────

def test_an_extreme_outlier_fires_the_top_band_once():
    p = profile(40)
    r = payer(p, 48_000)                      # 78x the mean, above max_amount
    assert r["comparison"]["amount_multiple"] == pytest.approx(78.69, abs=0.01)
    assert any("higher than the user's average payment" in x for x in r["reasons"])
    assert any("higher than any previously seen" in x for x in r["reasons"])
    assert r["facts"].count(Fact.AMOUNT_DEVIATION.value) == 1, (
        "two amount rules, one observation about the world"
    )


def test_the_ladder_is_monotonic_in_the_amount():
    p = profile(40)
    scores = [payer(p, a)["risk_score"] for a in (240, 2_000, 5_500, 12_000, 48_000)]
    assert scores == sorted(scores)


def test_the_model_reads_the_same_outlier_as_a_median_multiple():
    v = build_vector(amount=48_000.0, timestamp=TS, profile=profile(40),
                     reputation=ESTABLISHED_PAYEE, payer_seen_payee_before=True,
                     **NORMAL_VELOCITY)
    assert v.values["amount_over_user_avg"] == pytest.approx(48_000 / 220.0)
    assert v.available["amount_over_user_avg"] is True


# ── 5. The current payment is never part of its own baseline ─────────────────

def _statement(amounts, upi="canteen@ybl"):
    return [
        {"timestamp": f"2026-08-{1 + i:02d}T13:0{i % 6}:00", "amount": float(a),
         "merchant": "SRI LAKSHMI CANTEEN", "upi_id": upi, "status": "SUCCESS",
         "txn_type": "DEBIT"}
        for i, a in enumerate(amounts)
    ]


def test_the_profile_describes_the_statement_and_nothing_after_it():
    p = generate_behavior_profile(_statement([200, 210, 190, 260, 240, 220]))
    assert p["max_amount"] == 260.0
    assert p["avg_amount"] == pytest.approx(220.0, abs=0.01)
    assert p["median_amount"] == pytest.approx(215.0, abs=0.01)


def test_the_payment_being_judged_is_not_in_the_statistic_it_is_judged_against():
    """The pre-payment decision path scores a payment that does not exist yet.
    If its own amount leaked into the denominator the ratio would shrink towards
    1.0 and a large payment would argue itself normal."""
    p = generate_behavior_profile(_statement([200, 210, 190, 260, 240, 220]))
    r = payer(p, 9_000.0)
    assert r["comparison"]["average_amount"] == pytest.approx(220.0, abs=0.01)
    assert r["comparison"]["amount_multiple"] == pytest.approx(9_000 / 220.0, abs=0.1)
    assert any("higher than any previously seen" in x for x in r["reasons"]), (
        "Rs 9,000 is above the statement's Rs 260 maximum; it could only fail to "
        "fire if the amount had been folded into max_amount first"
    )


def test_a_credit_does_not_become_part_of_the_spending_baseline():
    """Salary in is not a payment out, and including it raises every denominator."""
    txns = _statement([200, 210, 190, 260, 240, 220])
    txns.append({"timestamp": "2026-08-30T10:00:00", "amount": 60_000.0,
                 "merchant": "EMPLOYER", "upi_id": "", "status": "SUCCESS",
                 "txn_type": "CREDIT"})
    p = generate_behavior_profile(txns)
    assert p["max_amount"] == 260.0
    assert p["avg_amount"] == pytest.approx(220.0, abs=0.01)


# ── 6. Identical historical amounts ──────────────────────────────────────────

def test_identical_history_gives_the_mean_and_the_median_the_same_value():
    p = generate_behavior_profile(_statement([200] * 8))
    assert p["avg_amount"] == 200.0 and p["median_amount"] == 200.0
    r = payer(p, 200.0)
    assert r["comparison"]["amount_multiple"] == 1.0
    assert amount_facts(r) == []
    v = build_vector(amount=200.0, timestamp=TS, profile=p, reputation=ESTABLISHED_PAYEE,
                     payer_seen_payee_before=True, **NORMAL_VELOCITY)
    assert v.values["amount_over_user_avg"] == 1.0


def test_a_flat_history_still_ranks_a_large_payment_the_same_way():
    """With no spread the two statistics agree, so both paths must say the
    same thing - this is the case that would expose a sign or inversion bug."""
    p = generate_behavior_profile(_statement([200] * 8))
    r = payer(p, 4_000.0)
    assert r["comparison"]["amount_multiple"] == 20.0
    assert any("higher than the user's average payment" in x for x in r["reasons"])


# ── 7. Zero and near-zero ────────────────────────────────────────────────────

def test_a_zero_baseline_is_not_divided_by():
    p = profile(40, avg=0.0, median=0.0, maximum=0.0)
    assert payer_baseline_amount(p) == 0.0
    assert amount_baseline_is_measurable(p) is False, (
        "a payment count with no amounts is not a baseline; the denominator "
        "would silently become the population constant"
    )
    r = payer(p, 5_000.0)                      # must not raise
    assert "amount_multiple" not in r["comparison"]


def test_a_zero_amount_disables_the_model_rather_than_scoring_zero():
    e = ml(profile(40), 0.0)
    assert e["available"] is False and e["score"] is None
    assert "amount" in e["message"]


def test_a_near_zero_amount_is_arithmetic_not_an_error():
    r = payer(profile(40), 0.01)
    assert r["comparison"]["amount_multiple"] == 0.0
    v = build_vector(amount=0.01, timestamp=TS, profile=profile(40),
                     reputation=ESTABLISHED_PAYEE, payer_seen_payee_before=True,
                     **NORMAL_VELOCITY)
    assert 0 < v.values["amount_over_user_avg"] < 0.001


def test_an_empty_statement_produces_a_profile_with_no_baseline():
    p = generate_behavior_profile([])
    assert payer_baseline_amount(p) == 0.0
    assert amount_baseline_is_measurable(p) is False


# ── 8. A profile with payments but no amount statistics ──────────────────────

def test_a_profile_missing_its_amount_statistics_reports_unavailable():
    """Reachable from an older stored profile. The failure it used to produce is
    the quiet one: POPULATION_MEDIAN_AMOUNT standing in for this payer's
    history, which is the same substitution the payee defaults used to make."""
    p = {"transaction_count": 300, "debit_count": 300, "most_active_hour": 19,
         "average_daily_transactions": 3.2}
    assert amount_baseline_is_measurable(p) is False
    e = ml(p, 48_000)
    assert e["available"] is False and e["score"] is None

    v = build_vector(amount=48_000.0, timestamp=TS, profile=p, reputation=ESTABLISHED_PAYEE,
                     payer_seen_payee_before=True, **NORMAL_VELOCITY)
    assert v.available["amount_over_user_avg"] is False


def test_a_profile_carrying_only_a_mean_falls_back_to_it():
    """median_amount post-dates the first profiles written; those must still
    work, and must use the figure they actually have."""
    p = {"transaction_count": 300, "debit_count": 300, "avg_amount": 300.0}
    assert payer_baseline_amount(p) == 300.0
    assert amount_baseline_is_measurable(p) is True
    v = build_vector(amount=600.0, timestamp=TS, profile=p, reputation=ESTABLISHED_PAYEE,
                     payer_seen_payee_before=True, **NORMAL_VELOCITY)
    assert v.values["amount_over_user_avg"] == 2.0
    assert v.available["amount_over_user_avg"] is True


# ── 9. Train/serve parity on the ratio ───────────────────────────────────────

def test_the_served_denominator_is_the_one_the_model_was_trained_on():
    """Training divides by typical_amount, the MEDIAN of the lognormal draw
    (exp(mu)). Serving must divide by median_amount, not avg_amount, or every
    ratio the model sees is systematically too small."""
    p = profile(40, avg=610.0, median=220.0)
    v = build_vector(amount=2_200.0, timestamp=TS, profile=p, reputation=ESTABLISHED_PAYEE,
                     payer_seen_payee_before=True, **NORMAL_VELOCITY)
    assert v.values["amount_over_user_avg"] == pytest.approx(10.0), "2200 / median 220"
    assert v.values["amount_over_user_avg"] != pytest.approx(2_200.0 / 610.0)


def test_training_ratios_are_centred_where_a_median_denominator_puts_them():
    df = generate(6_000, seed=11)
    legit = df.loc[df[LABEL] == 0, "amount_over_user_avg"]
    assert 0.5 < float(legit.median()) < 2.5, (
        "an ordinary payment is about one times the payer's typical amount; a "
        "mean denominator would pull this well below 1"
    )
    fraud = df.loc[df[LABEL] == 1, "amount_over_user_avg"]
    assert float(fraud.median()) > float(legit.median())


def test_the_served_vector_has_exactly_the_trained_columns_in_order():
    v = build_vector(amount=2_200.0, timestamp=TS, profile=profile(40),
                     reputation=ESTABLISHED_PAYEE, payer_seen_payee_before=True,
                     **NORMAL_VELOCITY)
    assert list(v.frame().columns) == list(FEATURES)
    assert "amount_over_user_avg" in FEATURES


def test_the_trained_ratio_is_never_a_sentinel():
    """NaN is the vocabulary for unavailable payee history. The amount ratio is
    not part of it: the model was not fitted with that column missing, so the
    family reports itself unavailable instead of passing a value the model has
    never seen."""
    for p in ({}, {"transaction_count": 300, "debit_count": 300}, profile(40)):
        v = build_vector(amount=1_000.0, timestamp=TS, profile=p,
                         reputation=ESTABLISHED_PAYEE, payer_seen_payee_before=True,
                         **NORMAL_VELOCITY)
        assert not np.isnan(v.values["amount_over_user_avg"])


# ── 10. The payer ladder against its documented definition ───────────────────

def test_the_ladder_denominator_is_the_mean_as_documented():
    """Deliberate, and measured: switching it to the median turns the demo
    payer's monthly rent from APPROVE into WARN, because against a median of
    222 the rent is 83x and sits in the same top band as fraud at 416x."""
    p = profile(40, avg=1_000.0, median=100.0, maximum=20_000.0)
    r = payer(p, 4_000.0)
    assert r["comparison"]["amount_multiple"] == 4.0, "4x the mean, not 40x the median"
    assert any("materially above" in x for x in r["reasons"])
    assert not any("higher than the user's average payment" in x for x in r["reasons"])


def test_the_documented_ladder_bands_are_the_ones_applied():
    p = profile(40, avg=1_000.0, median=1_000.0, maximum=1_000_000.0)
    bands = {a: payer(p, a)["risk_score"] for a in (2_000, 3_000, 8_000, 15_000)}
    assert bands[2_000] < bands[3_000] < bands[8_000] < bands[15_000]


def test_the_ladder_compares_the_exact_ratio_and_rounds_only_for_display():
    """14.996x reads as 15.0x. Rounding before comparing put it in the top band
    and jumped the score 11 points on a display artefact."""
    p = profile(40, avg=1_000.0, median=1_000.0, maximum=1_000_000.0)
    just_under = payer(p, 14_996.0)
    at = payer(p, 15_000.0)
    assert just_under["comparison"]["amount_multiple"] == 15.0
    assert just_under["risk_score"] < at["risk_score"]


def test_the_rent_payment_the_ladder_was_calibrated_for_stays_approved():
    """The demo payer: daily payments around Rs 220, rent at Rs 18,500. This is
    the case a median denominator breaks."""
    p = profile(120, avg=1_523.0, median=222.0, maximum=18_500.0,
                known_upi_ids=["landlord@okhdfcbank"],
                known_merchant_keys=["landlord"], favorite_merchants=["LANDLORD"])
    r = payer(p, 18_500.0, merchant="LANDLORD", upi_id="landlord@okhdfcbank")
    assert r["comparison"]["amount_multiple"] == pytest.approx(12.15, abs=0.05)
    assert not any("higher than the user's average payment" in x for x in r["reasons"]), (
        "12x the mean is the middle band; against the median it would be 83x"
    )


# ── The same amount fact, counted once ───────────────────────────────────────

CANTEEN = "srilakshmi.canteen@ybl"


def _rows(result):
    return {e["family"]: e for e in result["evidence"]}


def check(amount, timestamp=NIGHT, velocity=None, **kw):
    base = dict(
        payload="unknown.payee.9021@ybl", payer_id="u-amount", amount=amount,
        profile=profile(280), history=EMPTY_HISTORY, timestamp=timestamp,
        velocity=velocity or BURST_VELOCITY,
    )
    base.update(kw)
    return check_payee(**base)


def test_both_behavioural_families_can_observe_the_amount():
    r = check(48_000.0)
    rows = _rows(r)
    observers = r["agreement"]["observed_by"].get(Fact.AMOUNT_DEVIATION.value, [])
    assert rows[Family.PAYER_BEHAVIOUR.value]["available"] is True
    assert Fact.AMOUNT_DEVIATION.value in rows[Family.PAYER_BEHAVIOUR.value]["facts"]
    assert len(observers) >= 1


def test_the_amount_fact_is_counted_once_however_many_families_report_it():
    r = check(48_000.0)
    facts = r["agreement"]["facts"]
    assert facts.count(Fact.AMOUNT_DEVIATION.value) <= 1
    assert len(facts) == len(set(facts)), "the bonus counts distinct observations"


def test_the_bonus_is_bounded_by_the_number_of_reporting_families():
    """Five facts observed by three families is three streams agreeing, not
    five. Without this bound the payer rules noticing a payment's size AND its
    hour paid the same bonus as two independent modules agreeing."""
    r = check(48_000.0)
    families = {name for observers in r["agreement"]["observed_by"].values()
                for name in observers}
    facts = r["agreement"]["facts"]
    assert len(facts) >= len(families), "this case is only interesting when facts exceed families"
    assert r["agreement"]["bonus"] == AGREEMENT_BONUS[min(len(facts), len(families))]


def test_the_amount_context_family_measures_a_different_thing():
    """Rail caps and "large to a stranger" are facts about the amount itself,
    not about this payer, so they are a separate observation - and must not be
    tagged as the payer-relative one."""
    rows = _rows(check(48_000.0))
    ctx = rows[Family.AMOUNT_CONTEXT.value]
    assert ctx["available"] is True
    assert Fact.AMOUNT_ABSOLUTE.value in ctx["facts"]
    assert Fact.AMOUNT_DEVIATION.value not in ctx["facts"]


def test_a_payer_with_no_amount_baseline_contributes_no_amount_deviation():
    r = check(48_000.0, profile=profile(1, avg=10.0, median=10.0, maximum=10.0))
    rows = _rows(r)
    assert rows[Family.ML_CLASSIFIER.value]["available"] is False
    assert Fact.AMOUNT_DEVIATION.value not in (
        rows[Family.PAYER_BEHAVIOUR.value]["facts"] or []
    )
    assert Fact.AMOUNT_DEVIATION.value not in r["agreement"]["facts"]


def test_an_unavailable_amount_comparison_lowers_confidence_not_risk():
    """The two payers differ only in how much history they have. The thin one
    must not come out safer for it."""
    thin = check(48_000.0, profile=profile(1, avg=10.0, median=10.0, maximum=10.0))
    rich = check(48_000.0)
    assert thin["confidence_score"] < rich["confidence_score"]
    assert thin["risk_score"] <= rich["risk_score"]
    assert Family.ML_CLASSIFIER.value in thin["missing_evidence"]
