"""Unavailable evidence must never read as evidence of safety.

The bug these guard against is quiet. Nothing crashes, no metric collapses,
and the system goes on returning confident low scores for payees it knows
nothing about - which is precisely the population a mule account belongs to.

Three properties are asserted here, and they are not the same property:

  1. Absence is represented as absence.       NaN, never a stand-in constant.
  2. Absence is distinguishable from zero.    A measured 0 and a missing value
                                              must not collide.
  3. Absence does not encode the label.       The generator hides payee history
                                              where a deployment would not have
                                              it, and that mask must not become
                                              a proxy for "fraud" or for "safe".

Every test here fails against the version that substituted 180 days / 8 payers
/ 0.4 repeat ratio for an unknown payee.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.ml.dataset import (
    FEATURES,
    LABEL,
    PAYEE_HISTORY_FEATURES,
    availability_bias,
    generate,
)
from backend.app.core.entity_status import MIN_PAYERS_FOR_SHAPE
from backend.ml.features import build_vector

ESTABLISHED = {"known": True, "age_days": 640, "distinct_payers": 55, "repeat_payers": 38}
TOO_FEW_PAYERS = {"known": True, "age_days": 12, "distinct_payers": 2, "repeat_payers": 0}


# ── 1. Absence is absence ────────────────────────────────────────────────────

@pytest.mark.parametrize("reputation, why", [
    ({}, "no reputation at all"),
    ({"known": False}, "explicitly not known"),
    ({"known": True}, "known but carrying no figures"),
    ({"known": True, "age_days": None, "distinct_payers": 40}, "age missing"),
])
def test_no_payee_record_produces_no_payee_features(reputation, why):
    v = build_vector(2500, "2026-09-09T13:00:00", reputation=reputation)
    for name in PAYEE_HISTORY_FEATURES:
        assert math.isnan(v.values[name]), f"{name} was invented when {why}"
        assert v.available[name] is False
    assert v.values["payee_history_available"] == 0.0


def test_a_thin_record_keeps_its_counts_and_withholds_only_the_ratio():
    """Counts are facts; a ratio over two payers is not.

    This distinction was got wrong first time round. Everything about a thin
    payee was withheld together, on the reasoning that two payers cannot
    support a repeat-payer ratio - which is true, and does not apply to the
    other two features. An address first seen six days ago with two payers IS
    six days old and DOES have two payers, both measured exactly, and they are
    the two signals a young collection account gives itself away on.
    Withholding them cost the demo's account-takeover case its detection and
    taught the lesson that "unavailable" has to be decided per feature and not
    per family.
    """
    v = build_vector(2500, "2026-09-09T13:00:00", reputation=TOO_FEW_PAYERS)

    assert v.values["payee_age_days"] == 12
    assert v.values["payee_distinct_payers"] == 2
    assert v.available["payee_age_days"] is True
    assert v.available["payee_distinct_payers"] is True
    assert v.values["payee_history_available"] == 1.0

    # The estimate, and only the estimate, waits for a sample worth the name.
    assert math.isnan(v.values["payee_repeat_ratio"])
    assert v.available["payee_repeat_ratio"] is False


def test_a_readable_payee_reports_measured_values():
    v = build_vector(2500, "2026-09-09T13:00:00", reputation=ESTABLISHED)
    assert v.values["payee_age_days"] == 640
    assert v.values["payee_distinct_payers"] == 55
    assert v.values["payee_repeat_ratio"] == pytest.approx(38 / 55)
    assert all(v.available[n] for n in PAYEE_HISTORY_FEATURES)
    assert v.values["payee_history_available"] == 1.0


def test_no_payee_feature_is_ever_a_population_constant():
    """The specific defaults that used to be substituted, named so that
    reintroducing any of them fails here rather than silently."""
    v = build_vector(2500, None, reputation={})
    assert v.values["payee_age_days"] != 180.0
    assert v.values["payee_distinct_payers"] != 8.0
    assert v.values["payee_repeat_ratio"] != 0.4


# ── 2. Absence is distinguishable from zero ──────────────────────────────────

def test_a_measured_zero_is_not_the_same_as_unavailable():
    """The distinction the whole change set rests on.

    A payee with 40 payers and no repeat customers has a repeat ratio of
    exactly 0.0, and that is a strong, real signal. A payee nobody has seen
    has no repeat ratio at all. If both arrive at the model as 0.0 then every
    unknown address inherits the risk profile of a collection account, and if
    both arrive as 0.4 then every collection account inherits the profile of
    an ordinary payee. Neither is acceptable, and telling them apart is the
    only way to avoid both.
    """
    measured = build_vector(
        2500, None,
        reputation={"known": True, "age_days": 6, "distinct_payers": 40, "repeat_payers": 0},
    )
    unavailable = build_vector(2500, None, reputation={})

    assert measured.values["payee_repeat_ratio"] == 0.0
    assert measured.available["payee_repeat_ratio"] is True
    assert math.isnan(unavailable.values["payee_repeat_ratio"])
    assert unavailable.available["payee_repeat_ratio"] is False
    assert measured.values["payee_history_available"] != \
        unavailable.values["payee_history_available"]


def test_missing_lists_exactly_what_could_not_be_measured():
    v = build_vector(2500, "2026-09-09T13:00:00", reputation={}, payer_seen_payee_before=False)
    missing = v.missing()
    assert set(PAYEE_HISTORY_FEATURES) <= set(missing)
    assert "payee_is_new" not in missing, "payer-relative, and the payer was supplied"
    assert "amount" not in missing


def test_payer_relative_features_survive_an_unknown_payee():
    """Knowing nothing about the payee must not cost us what we know about the
    payer. A first payment to a stranger is still scoreable on the payer's own
    behaviour, and refusing to score it at all would make the system useless
    for exactly the case it exists for."""
    v = build_vector(
        95_000, "2026-09-09T03:40:00",
        profile={"median_amount": 220, "most_active_hour": 19, "average_daily_transactions": 3},
        reputation={}, payer_seen_payee_before=False,
    )
    assert v.available["amount_over_user_avg"] is True
    assert v.values["amount_over_user_avg"] > 400
    assert v.values["is_night"] == 1.0
    assert v.values["payee_is_new"] == 1.0


# ── 3. Absence does not encode the label ─────────────────────────────────────

def test_the_generator_hides_payee_history_on_a_substantial_minority():
    df = generate(n_transactions=20_000, seed=11)
    hidden = df["payee_history_available"] == 0.0
    share = float(hidden.mean())
    assert 0.10 < share < 0.50, (
        f"{share:.1%} of rows hidden. Too few and the model never learns what "
        "an unobserved payee looks like; too many and it learns little else."
    )
    for name in PAYEE_HISTORY_FEATURES:
        assert df.loc[hidden, name].isna().all(), f"{name} survived on an unobserved row"

    # Observed rows keep their counts unconditionally; the ratio is additionally
    # withheld where the sample is too thin to estimate one, so it is the only
    # column allowed to carry NaN on an observed row.
    observed = df.loc[~hidden]
    assert not observed["payee_age_days"].isna().any()
    assert not observed["payee_distinct_payers"].isna().any()
    thin = observed["payee_distinct_payers"] < MIN_PAYERS_FOR_SHAPE
    assert observed.loc[thin, "payee_repeat_ratio"].isna().all()
    assert not observed.loc[~thin, "payee_repeat_ratio"].isna().any()


def test_availability_is_not_a_proxy_for_the_label():
    """The guard that makes the mask honest.

    An unobserved payee is genuinely a little more likely to be a collection
    account, so a small positive bias is expected and correct. What must not
    happen is the gap growing large enough that the model can skip reading the
    evidence and score on availability alone - at which point every honest
    first payment to a stranger gets a warning, users learn to dismiss
    warnings, and the system protects nobody.
    """
    df = generate(n_transactions=40_000, seed=12)
    bias = availability_bias(df)
    hidden = df["payee_history_available"] == 0.0
    ratio = df.loc[hidden, LABEL].mean() / max(df.loc[~hidden, LABEL].mean(), 1e-9)

    assert bias > 0, "no bias at all would mean the mask ignores payer count"
    assert bias < 0.02, f"availability bias {bias:.4f} is large enough to be a shortcut"
    assert ratio < 3.0, f"unobserved payees are {ratio:.1f}x more fraudulent - too separable"


def test_availability_alone_cannot_discriminate():
    """State it as the model would see it: the flag on its own is near-useless."""
    from sklearn.metrics import roc_auc_score

    df = generate(n_transactions=40_000, seed=13)
    auc = roc_auc_score(df[LABEL], 1.0 - df["payee_history_available"])
    assert auc < 0.62, (
        f"payee_history_available alone reaches ROC-AUC {auc:.3f}; the model "
        "could learn 'unknown payee = fraud' from it and nothing else"
    )


def test_every_feature_column_is_present_and_ordered():
    df = generate(n_transactions=2_000, seed=14)
    assert list(df.columns)[:len(FEATURES)] == FEATURES
    v = build_vector(100, None)
    assert list(v.frame().columns) == FEATURES
    assert set(v.values) == set(FEATURES)


def test_the_fitted_model_accepts_an_unavailable_payee():
    """End to end: a NaN-carrying vector must score without raising.

    HistGradientBoosting reads NaN natively, but only a model trained on rows
    that contained NaN has learned a response to it. If the artefact were ever
    rebuilt from a generator without the observation mask, this is where that
    would surface.
    """
    model = pytest.importorskip("backend.models.ensemble_model", reason="model deps")
    try:
        fitted = model.load_model()
    except RuntimeError as exc:
        pytest.skip(f"no trained model here: {exc}")

    v = build_vector(
        18_000, "2026-09-09T11:32:00",
        profile={"median_amount": 220, "most_active_hour": 19, "average_daily_transactions": 3},
        reputation={}, payer_seen_payee_before=False,
    )
    assert v.frame().isna().any().any(), "this case is supposed to carry NaN"
    p = float(fitted.predict_proba(v.frame())[0, 1])
    assert 0.0 <= p <= 1.0
