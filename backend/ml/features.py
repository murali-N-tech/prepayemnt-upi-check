"""Build the model's feature vector from what the system knows at decision time.

This is the single place that mapping lives, so training and serving cannot
drift apart. Both backend/train_model.py and the FastAPI inference path import
from here; neither holds a copy.

What changed, and why it is the most important thing in this module
------------------------------------------------------------------
This file used to substitute constants when the payee was unknown:

    payee_age_days        -> 180.0
    payee_distinct_payers -> 8.0
    payee_repeat_ratio    -> 0.4

Those three numbers describe a moderately established payee with a modest but
real track record. So every address the system had never seen - which is every
address a first-time payer pays, and every address a mule opened last week -
was scored as though it had one. The defining property of a collection account
is that it has no history, and the code was inventing one for it.

The values are now NaN, and a companion feature says so explicitly:

    payee_history_available  1.0 measured, 0.0 unavailable

Two things had to change together for that to be safe. The generator now hides
payee history on a quarter of its rows (backend/ml/dataset.apply_observation_mask),
so "unavailable" is a case the model has actually seen and learned a response
to. And HistGradientBoostingClassifier handles NaN natively, routing it down
whichever branch the training data supports rather than needing an imputed
value at all. Passing NaN to a model trained without NaN would have been the
same bug wearing a different mask.

The distinction the pipeline now preserves end to end:

    0.0  measured zero   - we looked, and the answer is none
    NaN  unavailable     - we could not look

Collapsing those two is how an unknown entity gets classified as a low-risk
one, and the whole point of the evidence-availability work is that it cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from backend.ml.dataset import FEATURES

# Used only for the payer's own spending scale, and only when the payer has no
# profile yet. Unlike the payee defaults this one is defensible: it is a
# denominator, the alternative (dividing by the payment's own amount) makes
# amount_over_user_avg exactly 1.0 for every profile-less payer so a 48,000
# rupee transfer looks perfectly average, and the population median is a real
# estimate of an unknown payer's scale rather than an invented history.
POPULATION_MEDIAN_AMOUNT = 300.0

# How many of the payer's own payments are needed before "unusual for them"
# means anything.
#
# Below this, the baseline IS the outlier. A payer whose only prior payment
# was Rs 10 has a median of Rs 10, so an ordinary Rs 5,000 transfer reads as
# 500x their norm and the payer-behaviour rules score it 87. That is not a
# measurement of anything; it is one data point being asked to describe a
# distribution. The same reasoning as MIN_PAYERS_FOR_SHAPE on the payee side,
# applied to the payer.
#
# Five, matching MIN_PAYERS_FOR_SHAPE, because the two answer the same kind of
# question and there is no reason for them to disagree.
MIN_PAYMENTS_FOR_AMOUNT_BASELINE = 5


def payer_baseline_amount(profile: Optional[dict[str, Any]]) -> float:
    """The payer's own typical payment, or 0.0 when it cannot be read.

    Median first, because that is the denominator the model was trained on
    (see build_vector below); the mean is the fallback for profiles written
    before median_amount existed. 0.0 means "no baseline", not "a baseline of
    zero" - the callers treat it as the former and none of them divide by it.
    """
    if not profile:
        return 0.0
    median = float(profile.get("median_amount") or 0)
    if median > 0:
        return median
    return float(profile.get("avg_amount") or 0)


def amount_baseline_is_measurable(profile: Optional[dict[str, Any]]) -> bool:
    """Has this payer made enough payments for their own norm to be readable?

    Two conditions, and both are about the same thing - whether "unusual for
    them" refers to a measurement or to an assumption.

    Enough payments: counts spend, not all activity, because a profile of
    forty credits and one debit describes someone receiving money and says
    nothing about what they normally send.

    And an actual figure to compare against. A profile can carry a payment
    count with no amount statistics at all (an older stored profile, a
    hand-built one in a test), and in that state the denominator silently
    becomes POPULATION_MEDIAN_AMOUNT - a population constant wearing the
    clothes of this payer's history. That is the same substitution the payee
    defaults used to make, and it is refused here for the same reason.
    """
    if not profile:
        return False
    spend = profile.get("debit_count")
    if spend is None:
        spend = profile.get("transaction_count")
    if int(spend or 0) < MIN_PAYMENTS_FOR_AMOUNT_BASELINE:
        return False
    return payer_baseline_amount(profile) > 0

# Payee features that are measured together or not at all. They all come from
# the same reputation row, so there is no state in which one is knowable and
# the others are not.
PAYEE_HISTORY_FEATURES = ("payee_age_days", "payee_distinct_payers", "payee_repeat_ratio")


@dataclass
class FeatureVector:
    """Feature values plus an explicit record of which ones were measured.

    Carrying availability alongside the values, rather than encoding it in
    them, is what lets the caller answer "could the model see the payee at
    all?" without reverse-engineering it from a sentinel.
    """

    values: dict[str, float]
    available: dict[str, bool] = field(default_factory=dict)

    @property
    def payee_history_available(self) -> bool:
        return bool(self.values.get("payee_history_available", 0.0))

    def missing(self) -> list[str]:
        return sorted(name for name, ok in self.available.items() if not ok)

    def frame(self) -> pd.DataFrame:
        """Column order matters to the fitted pipeline; never rely on dict order."""
        return pd.DataFrame([[self.values[name] for name in FEATURES]], columns=FEATURES)

    def as_dict(self) -> dict[str, float]:
        return dict(self.values)


def _hour_of(timestamp: str | None) -> int:
    if not timestamp:
        return datetime.now(timezone.utc).hour
    try:
        return int(pd.to_datetime(timestamp, errors="coerce").hour)
    except (ValueError, TypeError):
        return 12


def _payee_is_new(payer_seen_payee_before: Optional[bool],
                  reputation: dict[str, Any]) -> float:
    """1.0 when this payer has not paid this payee before.

    Payer-relative, and therefore answerable even when nothing is known about
    the payee: the payer's own history is ours to read. When there is no payer
    to ask about, fall back to whether the payee has been seen at all - a
    weaker question, stated here rather than hidden.
    """
    if payer_seen_payee_before is not None:
        return 0.0 if payer_seen_payee_before else 1.0
    return 0.0 if reputation.get("known") else 1.0


def _counts_are_measured(reputation: dict[str, Any]) -> bool:
    """Do we have the payee's age and payer count as facts?

    These are counts, not estimates. An address first seen six days ago with
    two payers IS six days old and DOES have two payers, and both are precise
    however small they are. Withholding them would discard real evidence, and
    they are the two strongest signals a young collection account emits.
    """
    if not reputation.get("known"):
        return False
    return reputation.get("distinct_payers") is not None \
        and reputation.get("age_days") is not None


def _shape_is_measurable(reputation: dict[str, Any]) -> bool:
    """Does the repeat-payer ratio mean anything yet?

    This is a different question from the one above, and an earlier version of
    this module ran the two together - withholding age and payer count
    whenever the ratio was too thin to trust. That cost the system its best
    signal on exactly the payees it most needed one for: a six-day-old address
    with two payers had all three features hidden and scored like an ordinary
    stranger.

    A ratio is an estimate over a sample. Two payers who each paid once give
    exactly 0.0, which is the signature of a collection account and is in fact
    an empty sample. So the ratio alone waits for a floor; the counts do not.
    """
    from backend.app.core.entity_status import MIN_PAYERS_FOR_SHAPE

    if not _counts_are_measured(reputation):
        return False
    return float(reputation["distinct_payers"]) >= MIN_PAYERS_FOR_SHAPE


def build_vector(
    amount: float,
    timestamp: str | None,
    profile: Optional[dict[str, Any]] = None,
    reputation: Optional[dict[str, Any]] = None,
    seconds_since_last_txn: float = 9000.0,
    txns_last_hour: float = 0.0,
    txns_today: float = 1.0,
    payer_seen_payee_before: Optional[bool] = None,
) -> FeatureVector:
    """One transaction -> the feature vector the model expects, plus availability."""
    profile = profile or {}
    reputation = reputation or {}
    amount = float(amount or 0)

    # The training denominator is the payer's MEDIAN payment. Serving divided
    # by the mean for a while, which for this spread runs about 1.44x larger,
    # so every served ratio came out ~30% too small and the model was
    # systematically under-sensitive on its strongest payer feature.
    measured_baseline = payer_baseline_amount(profile)
    user_avg = measured_baseline or POPULATION_MEDIAN_AMOUNT
    profile_available = bool(profile)
    usual_hour = profile.get("most_active_hour")
    hour = _hour_of(timestamp)
    if usual_hour is None:
        hours_from_usual = 0.0        # unknown, not "maximally unusual"
    else:
        diff = abs(hour - int(usual_hour))
        hours_from_usual = float(min(diff, 24 - diff))

    daily_avg = float(profile.get("average_daily_transactions") or 0) or 1.0

    counted = _counts_are_measured(reputation)
    shaped = _shape_is_measurable(reputation)
    payers = reputation.get("distinct_payers")
    repeats = reputation.get("repeat_payers")

    values: dict[str, float] = {
        "amount": amount,
        "amount_over_user_avg": amount / user_avg,
        "is_night": float(hour < 6 or hour >= 22),
        "hours_from_usual": hours_from_usual,
        "seconds_since_last_txn": float(seconds_since_last_txn),
        "txns_last_hour": float(txns_last_hour),
        "txns_today_over_avg": float(txns_today) / daily_avg,
        "payee_is_new": _payee_is_new(payer_seen_payee_before, reputation),
        # NaN, not a stand-in. See the module docstring.
        "payee_age_days": float(reputation["age_days"]) if counted else np.nan,
        "payee_distinct_payers": float(payers) if counted else np.nan,
        "payee_repeat_ratio": (
            float(repeats or 0) / max(float(payers or 0), 1.0) if shaped else np.nan
        ),
        "payee_history_available": 1.0 if counted else 0.0,
    }

    available = {
        "amount": True,
        # The ratio is only a measurement when the denominator is one. A
        # profile with no amount statistics still yields a number here - it is
        # just a number about the population, not about this payer.
        "amount_over_user_avg": measured_baseline > 0,
        "is_night": timestamp is not None,
        "hours_from_usual": usual_hour is not None,
        "seconds_since_last_txn": profile_available,
        "txns_last_hour": profile_available,
        "txns_today_over_avg": profile_available,
        "payee_is_new": payer_seen_payee_before is not None,
        "payee_age_days": counted,
        "payee_distinct_payers": counted,
        "payee_repeat_ratio": shaped,
        "payee_history_available": True,
    }

    return FeatureVector(values=values, available=available)


def build_features(*args: Any, **kwargs: Any) -> dict[str, float]:
    """Backwards-compatible shim returning just the values.

    Callers that need to know what was measured should use build_vector.
    """
    return build_vector(*args, **kwargs).as_dict()


def to_frame(features: dict[str, float]) -> pd.DataFrame:
    """Column order matters to the fitted pipeline; never rely on dict order."""
    return pd.DataFrame([[features[name] for name in FEATURES]], columns=FEATURES)
