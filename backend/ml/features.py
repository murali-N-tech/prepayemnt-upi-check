"""Build the model's feature vector from what the system knows at decision time.

The model is only useful if the features it was trained on can actually be
computed for a live payment. This is the single place that mapping lives, so
training and serving cannot drift apart - the previous setup trained on five
made-up columns and served a different five.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from backend.ml.dataset import FEATURES

# Used only when the payer has no behaviour profile yet. Taken from the median
# legitimate payment in the training distribution. Falling back to the payment's
# own amount instead makes amount_over_user_avg exactly 1.0 for every
# profile-less user, so a 48,000 rupee transfer looks perfectly average.
POPULATION_MEDIAN_AMOUNT = 300.0


def _hour_of(timestamp: str | None) -> int:
    if not timestamp:
        return datetime.now(timezone.utc).hour
    try:
        return int(pd.to_datetime(timestamp, errors="coerce").hour)
    except (ValueError, TypeError):
        return 12


def build_features(
    amount: float,
    timestamp: str | None,
    profile: Optional[dict[str, Any]] = None,
    reputation: Optional[dict[str, Any]] = None,
    seconds_since_last_txn: float = 9000.0,
    txns_last_hour: float = 0.0,
    txns_today: float = 1.0,
    payer_seen_payee_before: Optional[bool] = None,
) -> dict[str, float]:
    """One transaction -> the feature dict the model expects.

    Missing inputs fall back to population-typical values rather than zeros: a
    zero payee_age_days means "brand new account", which is a strong fraud
    signal, so defaulting an unknown payee to zero would invent one.
    """
    profile = profile or {}
    reputation = reputation or {}

    amount = float(amount or 0)

    # The training denominator is the user's MEDIAN payment (dataset.py draws
    # amounts as exp(normal(log(typical), sigma)), so `typical_amount` is the
    # median). Serving used to divide by the mean, which for that spread is
    # about 1.44x larger - so every served ratio came out ~30% too small and
    # the model was systematically under-sensitive on its strongest payer
    # feature. Use the median, and fall back to the mean only for profiles
    # written before it was recorded.
    user_avg = (
        float(profile.get("median_amount") or 0)
        or float(profile.get("avg_amount") or 0)
        or POPULATION_MEDIAN_AMOUNT
    )
    usual_hour = profile.get("most_active_hour")
    hour = _hour_of(timestamp)

    if usual_hour is None:
        hours_from_usual = 0.0        # unknown, not "maximally unusual"
    else:
        diff = abs(hour - int(usual_hour))
        hours_from_usual = float(min(diff, 24 - diff))

    daily_avg = float(profile.get("average_daily_transactions") or 0) or 1.0

    known = bool(reputation.get("known"))
    return {
        "amount": amount,
        "amount_over_user_avg": amount / user_avg,
        "is_night": float(hour < 6 or hour >= 22),
        "hours_from_usual": hours_from_usual,
        "seconds_since_last_txn": float(seconds_since_last_txn),
        "txns_last_hour": float(txns_last_hour),
        "txns_today_over_avg": float(txns_today) / daily_avg,
        # Trained meaning: "this PAYER has not paid this PAYEE before". The
        # previous rule here asked whether the payee had any repeat payers at
        # all, which is a fact about the payee's whole network and is true for
        # nearly every payee - so the feature was pinned near 0 in production
        # while training had it at 1 for 95% of fraud.
        "payee_is_new": _payee_is_new(payer_seen_payee_before, reputation),
        # `age_days` is None when the payee has payers but no reputation row
        # yet. Guarding on `known` let that None become 0.0 - a zero-day-old
        # account, which is the single strongest mule signal there is.
        "payee_age_days": (
            float(reputation["age_days"])
            if known and reputation.get("age_days") is not None
            else 180.0
        ),
        "payee_distinct_payers": (
            float(reputation["distinct_payers"])
            if known and reputation.get("distinct_payers")
            else 8.0
        ),
        "payee_repeat_ratio": (
            float(reputation.get("repeat_payers") or 0)
            / max(float(reputation.get("distinct_payers") or 0), 1.0)
            if known
            else 0.4
        ),
    }


def _payee_is_new(payer_seen_payee_before: Optional[bool],
                  reputation: dict[str, Any]) -> float:
    """1.0 when this payer has not paid this payee before.

    When there is no payer to ask about, fall back to whether we have ever
    seen the payee at all. That is a weaker question, but it is one we can
    actually answer, and it is stated here rather than hidden.
    """
    if payer_seen_payee_before is not None:
        return 0.0 if payer_seen_payee_before else 1.0
    return 0.0 if reputation.get("known") else 1.0


def to_frame(features: dict[str, float]) -> pd.DataFrame:
    """Column order matters to the fitted pipeline; never rely on dict order."""
    return pd.DataFrame([[features[name] for name in FEATURES]], columns=FEATURES)
