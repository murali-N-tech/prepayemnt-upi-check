"""The dataset, the feature contract, and what the model must not be.

The regression these guard against: a classifier trained on random numbers
whose labels were a rule over those same numbers, served with a different
feature set than it was trained on.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backend.ml.dataset import FEATURES, LABEL, PAYEE_FEATURES, PAYER_FEATURES, generate
from backend.ml.features import build_features, to_frame

ROOT = Path(__file__).resolve().parents[1]


# ── The dataset ───────────────────────────────────────────────────────────

def test_labels_are_not_a_rule_over_the_features():
    """The old script labelled rows with
       amount > 80000 | rolling_txn_count > 7 | time_gap < 50
    so the label was a deterministic function of the features. If any single
    feature threshold separates the classes perfectly, we have rebuilt that.
    """
    df = generate(20_000, seed=7)
    for col in FEATURES:
        legit = df.loc[df[LABEL] == 0, col]
        fraud = df.loc[df[LABEL] == 1, col]
        overlap = (legit.min() <= fraud.max()) and (fraud.min() <= legit.max())
        assert overlap, f"{col} separates the classes with no overlap"


def test_fraud_and_legitimate_ranges_genuinely_overlap():
    """Honest payments to new payees, and large honest payments, must exist -
    otherwise the problem is trivial and the metrics are meaningless."""
    df = generate(20_000, seed=7)
    legit = df[df[LABEL] == 0]
    assert legit["payee_is_new"].mean() > 0.10
    assert (legit["amount_over_user_avg"] > 5).mean() > 0.03
    fraud = df[df[LABEL] == 1]
    assert (fraud["payee_age_days"] > 180).mean() > 0.05


def test_every_scenario_is_represented():
    df = generate(30_000, seed=3)
    kinds = set(df.loc[df[LABEL] == 1, "scenario"])
    assert kinds == {"social_engineering", "mule_collection", "account_takeover", "card_testing"}


def test_feature_groups_partition_the_feature_set():
    assert set(PAYER_FEATURES) | set(PAYEE_FEATURES) == set(FEATURES)
    assert not set(PAYER_FEATURES) & set(PAYEE_FEATURES)


def test_generation_is_reproducible():
    a = generate(2_000, seed=11)
    b = generate(2_000, seed=11)
    assert a[FEATURES].equals(b[FEATURES])


# ── The serving feature contract ──────────────────────────────────────────

def test_build_features_produces_exactly_the_trained_columns():
    f = build_features(amount=500, timestamp="2026-09-09T13:00:00")
    assert set(f) == set(FEATURES)
    assert list(to_frame(f).columns) == FEATURES


def test_column_order_is_fixed_not_dict_order():
    f = build_features(amount=500, timestamp="2026-09-09T13:00:00")
    shuffled = dict(reversed(list(f.items())))
    assert list(to_frame(shuffled).columns) == FEATURES
    assert to_frame(shuffled).equals(to_frame(f))


def test_an_unknown_payee_is_not_reported_as_a_zero_day_account():
    """Defaulting a missing age to 0 invents the strongest fraud signal there
    is. An unknown payee must fall back to something population-typical."""
    f = build_features(amount=500, timestamp="2026-09-09T13:00:00", reputation={})
    assert f["payee_age_days"] > 0
    assert f["payee_distinct_payers"] > 0


def test_known_payee_values_come_from_the_reputation_store():
    f = build_features(
        amount=500, timestamp="2026-09-09T13:00:00",
        reputation={"known": True, "age_days": 9, "distinct_payers": 24, "repeat_payers": 0},
    )
    assert f["payee_age_days"] == 9
    assert f["payee_distinct_payers"] == 24
    assert f["payee_repeat_ratio"] == 0
    assert f["payee_is_new"] == 1


def test_night_and_hour_distance():
    night = build_features(amount=100, timestamp="2026-09-09T23:30:00",
                           profile={"most_active_hour": 13})
    assert night["is_night"] == 1
    assert night["hours_from_usual"] == pytest.approx(10)

    day = build_features(amount=100, timestamp="2026-09-09T13:00:00",
                         profile={"most_active_hour": 13})
    assert day["is_night"] == 0
    assert day["hours_from_usual"] == 0


def test_unknown_usual_hour_is_not_treated_as_maximally_unusual():
    f = build_features(amount=100, timestamp="2026-09-09T03:00:00", profile={})
    assert f["hours_from_usual"] == 0


# ── The published metrics ─────────────────────────────────────────────────

@pytest.mark.skipif(not (ROOT / "models" / "metrics.json").exists(),
                    reason="run python backend/train_model.py first")
def test_metrics_report_what_matters_and_state_the_caveat():
    m = json.loads((ROOT / "models" / "metrics.json").read_text())
    assert "simulated" in m["data"]["source"]
    assert "No public labelled UPI fraud dataset" in m["data"]["caveat"]
    for key in ("pr_auc", "roc_auc", "operating_point", "recall_by_scenario"):
        assert key in m["selected"]
    assert m["selected"]["operating_point"]["fpr_budget"] == 0.01
    # A near-perfect PR-AUC on simulated data means the simulator is separable,
    # not that the model is good.
    assert m["selected"]["pr_auc"] < 0.95, "suspiciously high - check the generator"


@pytest.mark.skipif(not (ROOT / "models" / "metrics.json").exists(),
                    reason="run python backend/train_model.py first")
def test_the_ablation_supports_the_projects_claim():
    m = json.loads((ROOT / "models" / "metrics.json").read_text())
    se = m["ablation"]["social_engineering_recall"]
    assert se["both"] > se["payer_only"], (
        "payee signals must add something on the case the payer cannot see"
    )
