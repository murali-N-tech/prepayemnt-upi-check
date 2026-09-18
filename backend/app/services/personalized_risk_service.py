"""How unusual a payment is FOR THIS PAYER. One evidence family, not a verdict.

`risk_level` returns LOW / MEDIUM / HIGH and is kept only for the older
endpoints and dashboard panels that already render it. It is a display label
on one family's sub-score and it is NOT a decision about the payment.

The system has exactly one verdict vocabulary - APPROVE / WARN / STEP_UP /
BLOCK - and exactly one place that produces it, payee_check.check_payee, after
every family has been combined. A second scale used to leak into that decision
from here: /payee/check ran these rules separately and then nudged a payee-side
APPROVE up to WARN whenever this function happened to say HIGH. Two scales
meeting in an if-statement, with the damped-max rule and the agreement bonus
never seeing this score at all. That reconciliation is gone, check_payee reads
`risk_score` and `reasons` from here and nothing else, and `band` below exists
so any remaining caller can move to the canonical words.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from backend.app.core.verdict import level_from_score, verdict_from_score
from backend.app.services.evidence import Fact
from backend.ml.features import (
    amount_baseline_is_measurable as _amount_baseline_is_measurable,
)
from backend.app.services.merchant import merchant_key


def evaluate_personalized_risk(
    profile: dict[str, Any] | None,
    history: pd.DataFrame,
    amount: float,
    merchant: str,
    timestamp: str,
    upi_id: str | None = None,
    location: str | None = None,
    already_recorded: bool = False,
) -> dict[str, Any]:
    """`already_recorded` is True when this payment is already in `history` -
    the /monitor path re-scores stored rows, the pre-payment path does not.

    It corrects the velocity counts only, and cannot correct the amount
    statistics, because those arrive pre-computed in `profile`. So on the
    monitor path a stored row is compared against a baseline that includes
    itself: its own amount is inside avg_amount, and `amount > max_amount` can
    never fire for it. That is retrospective display, not a payment decision,
    and no verdict is issued from it. The decision path - check_payee, called
    before the payment exists - builds its profile from statements that end
    before the payment being judged, so nothing there is compared against
    itself or against anything later."""
    event_time = pd.to_datetime(timestamp, errors="coerce")
    if pd.isna(event_time):
        # Local, not UTC. Profile hours come from statement timestamps in local
        # time, and callers pass a local clock; utcnow() shifted the night
        # window by the UTC offset, so a 02:30 IST payment read as 21:00 and
        # the night rule did not fire.
        event_time = pd.Timestamp.now()

    if not profile or profile.get("transaction_count", 0) == 0:
        baseline_risk = 35 if amount > 10000 else 20
        return {
            "risk_score": int(baseline_risk),
            "risk_level": _level_from_score(baseline_risk),
            "band": band_from_score(baseline_risk),
            "facts": [],
            "reasons": [
                "No historical behavior profile found for this user",
                "Upload past UPI or bank statements to enable personalized checks",
            ],
            "comparison": {},
            "profile_available": False,
            "timestamp": event_time.isoformat(),
            "merchant": merchant,
            "location": location,
        }

    avg_amount = float(profile.get("avg_amount", 0) or 0)
    max_amount = float(profile.get("max_amount", 0) or 0)
    favorite_merchants = set(profile.get("favorite_merchants", []))
    known_upi_ids = set(profile.get("known_upi_ids", []))
    most_active_hour = profile.get("most_active_hour")
    avg_daily_transactions = float(profile.get("average_daily_transactions", 0) or 0)

    score = 5.0
    reasons: list[str] = []
    # Only the facts that actually fired, not every fact these rules could
    # read. A family that declares an observation it did not make would
    # corroborate on nothing.
    facts: set[str] = set()
    comparison: dict[str, Any] = {
        "average_amount": avg_amount,
        "max_amount": max_amount,
        "most_active_hour": most_active_hour,
        "average_daily_transactions": avg_daily_transactions,
    }

    # ── The amount ladder, and why its denominator is the MEAN ─────────────
    #
    # The model divides by the MEDIAN, because that is what it was trained on
    # (backend/ml/dataset typical_amount is exp(mu), the median of the
    # lognormal, and the parity is asserted in tests). This function divides
    # by the mean, and an audit checked whether that is an inconsistency worth
    # fixing. It is not, and the measurement is worth recording because the
    # obvious fix makes things worse.
    #
    # These are fixed thresholds - 15x, 8x, 3x - and a fixed ladder has to be
    # calibrated against the statistic it is applied to. On the demo payer,
    # whose spend is bimodal (daily payments around Rs 220, rent at Rs 18,500),
    # the mean is 1,523 and the median 222. Judged against the mean, the
    # monthly rent is 12x and lands in the middle band. Judged against the
    # median it is 83x, hits the top band, and turns an ordinary recurring
    # payment into a WARN every month. Worse, against the median both rent
    # (83x) and outright fraud (416x) sit in the same top band, so the ladder
    # loses all resolution exactly where it needs it.
    #
    # The model does not have this problem because it LEARNED the relationship
    # - its training population includes a pays_large segment - so it reads the
    # same rent at 83x and scores it 0.001. A learned function and a fixed
    # ladder need different denominators, and changing one without recalibrating
    # the other is how a correct-looking consistency fix introduces a false
    # positive.
    #
    # The mean's known weakness stands: it is dragged by outliers, including
    # fraudulent ones already in the payer's statement. The ladder was tuned on
    # means and is self-consistent with them; recalibrating both together is a
    # separate, deliberate piece of work, not a drive-by.
    if avg_amount > 0 and _amount_baseline_is_measurable(profile):
        # Compare the exact ratio and round only for display: rounding first
        # put 14.996 into the >= 15 band, an 11-point jump from a display
        # artefact that could cross the MEDIUM boundary on its own.
        exact_multiple = amount / avg_amount
        amount_multiple = round(exact_multiple, 2)
        comparison["amount_multiple"] = amount_multiple

        if exact_multiple >= 15:
            score += 35
            reasons.append(f"Amount is {amount_multiple}x higher than the user's average payment")
            facts.add(Fact.AMOUNT_DEVIATION.value)
        elif exact_multiple >= 8:
            score += 24
            reasons.append(f"Amount is {amount_multiple}x above the usual pattern")
            facts.add(Fact.AMOUNT_DEVIATION.value)
        elif exact_multiple >= 3:
            score += 12
            reasons.append(f"Amount is materially above the user's average transaction size")
            facts.add(Fact.AMOUNT_DEVIATION.value)

    if max_amount > 0 and amount > max_amount and _amount_baseline_is_measurable(profile):
        score += 15
        reasons.append("Amount is higher than any previously seen transaction in the uploaded statements")
        facts.add(Fact.AMOUNT_DEVIATION.value)

    # Compare canonical identities, not raw strings. "CHINTHADA MURALI
    # NAGARAJU" and "Chinthada Murali Nagaraju" are the same payee, and
    # comparing them with == made the heaviest merchant rule fire on ordinary
    # repeat payments.
    key = merchant_key(merchant, upi_id)
    known_keys = set(profile.get("known_merchant_keys") or [])
    if not known_keys:
        # Profile predates this field: derive the keys from the history.
        known_keys = {
            merchant_key(m, u)
            for m, u in zip(
                history.get("merchant", pd.Series(dtype=str)).astype(str).tolist(),
                history.get("upi_id", pd.Series(dtype=str)).astype(str).tolist(),
            )
        }
    known_keys.discard("")

    favourite_keys = set(profile.get("favorite_merchant_keys") or []) or {
        merchant_key(m) for m in favorite_merchants
    }

    if key and key not in known_keys and key not in favourite_keys:
        score += 20
        reasons.append("Merchant has not appeared in the user's historical statement profile")
        facts.add(Fact.PAYEE_FAMILIARITY.value)

    normalised_upi = (upi_id or "").strip().lower()
    if normalised_upi and normalised_upi not in {u.strip().lower() for u in known_upi_ids}:
        score += 12
        reasons.append("UPI ID is new for this user")
        facts.add(Fact.PAYEE_FAMILIARITY.value)

    hour = int(event_time.hour)
    if hour < 6 or hour >= 22:
        score += 12
        reasons.append("Transaction time falls in the user's higher-risk night window")
        facts.add(Fact.HOUR_ANOMALY.value)

    # Clock distance is circular. Straight subtraction made 02:00 look 21
    # hours from a 23:00 baseline instead of 3, so a night-shift user was
    # penalised on every ordinary payment. Every other hour comparison in this
    # codebase (ml/features.py, ml/dataset.py) already does this correctly.
    _hour_gap = abs(hour - int(most_active_hour)) if most_active_hour is not None else 0
    if most_active_hour is not None and min(_hour_gap, 24 - _hour_gap) >= 8:
        score += 8
        reasons.append("Transaction time is far from the user's most active payment hour")
        facts.add(Fact.HOUR_ANOMALY.value)

    daily_velocity = _projected_daily_velocity(history, event_time, already_recorded)
    comparison["projected_daily_transactions"] = daily_velocity
    if avg_daily_transactions > 0 and daily_velocity > max(avg_daily_transactions * 3, avg_daily_transactions + 6):
        score += 18
        reasons.append("Transaction velocity is unusually high compared with the user's normal daily activity")
        facts.add(Fact.VELOCITY_DAILY.value)

    failed_transactions = int(profile.get("failed_transactions", 0) or 0)
    total_transactions = int(profile.get("transaction_count", 0) or 0)
    if total_transactions > 0 and (failed_transactions / total_transactions) > 0.2:
        score += 5
        reasons.append("Historical statement profile already contains a high failed transaction ratio")
        facts.add(Fact.PAYER_RELIABILITY.value)

    score = min(99, round(score))

    if not reasons:
        reasons.append("Payment fits the user's historical amount, merchant, and timing patterns")

    return {
        "risk_score": int(score),
        "risk_level": _level_from_score(score),
        "band": band_from_score(score),
        "facts": sorted(facts),
        "reasons": reasons,
        "comparison": comparison,
        "profile_available": True,
        "timestamp": event_time.isoformat(),
        "merchant": merchant,
        "location": location,
    }


def _projected_daily_velocity(history: pd.DataFrame, event_time: pd.Timestamp,
                              counts_this_payment: bool = False) -> int:
    """Payments this payer has made today, including the one being scored.

    `counts_this_payment` says whether the payment is ALREADY in `history`.
    For a pre-payment check it is not, so one is added; for a stored
    transaction being re-scored it is, and adding one counted it twice -
    which pushed ordinary days over the velocity threshold and reported a
    number one higher than the truth back to the user.
    """
    if history.empty or "timestamp" not in history.columns:
        return 1

    history = history.copy()
    history["timestamp"] = pd.to_datetime(history["timestamp"], errors="coerce")
    same_day = history["timestamp"].dt.date == event_time.date()
    return int(same_day.sum()) + (0 if counts_this_payment else 1)


def _level_from_score(score: float) -> str:
    """Legacy LOW / MEDIUM / HIGH label. Not a verdict - see the docstring.

    Derived from the canonical band rather than from its own thresholds. It had
    its own ladder at 80 and 50, so this family could report a score of 75 as
    HIGH-band-BLOCK and MEDIUM in the same response: two vocabularies computed
    independently from one number, with nothing keeping them consistent.
    """
    return level_from_score(score)


def band_from_score(score: float) -> str:
    """This family's own sub-score in the canonical vocabulary.

    A thin alias for verdict_from_score, kept because callers already import
    this name. It describes one family's reading and is still not the payment's
    verdict: that comes from check_payee once every family has been combined.
    """
    return verdict_from_score(score)
