from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


def evaluate_personalized_risk(
    profile: dict[str, Any] | None,
    history: pd.DataFrame,
    amount: float,
    merchant: str,
    timestamp: str,
    upi_id: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    event_time = pd.to_datetime(timestamp, errors="coerce")
    if pd.isna(event_time):
        event_time = pd.Timestamp.utcnow()

    if not profile or profile.get("transaction_count", 0) == 0:
        baseline_risk = 35 if amount > 10000 else 20
        return {
            "risk_score": int(baseline_risk),
            "risk_level": _level_from_score(baseline_risk),
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
    comparison: dict[str, Any] = {
        "average_amount": avg_amount,
        "max_amount": max_amount,
        "most_active_hour": most_active_hour,
        "average_daily_transactions": avg_daily_transactions,
    }

    if avg_amount > 0:
        amount_multiple = round(amount / avg_amount, 2)
        comparison["amount_multiple"] = amount_multiple

        if amount_multiple >= 15:
            score += 35
            reasons.append(f"Amount is {amount_multiple}x higher than the user's average payment")
        elif amount_multiple >= 8:
            score += 24
            reasons.append(f"Amount is {amount_multiple}x above the usual pattern")
        elif amount_multiple >= 3:
            score += 12
            reasons.append(f"Amount is materially above the user's average transaction size")

    if max_amount > 0 and amount > max_amount:
        score += 15
        reasons.append("Amount is higher than any previously seen transaction in the uploaded statements")

    merchant_key = merchant.strip()
    if merchant_key not in favorite_merchants and merchant_key not in history.get("merchant", pd.Series(dtype=str)).astype(str).tolist():
        score += 20
        reasons.append("Merchant has not appeared in the user's historical statement profile")

    if upi_id and upi_id not in known_upi_ids:
        score += 12
        reasons.append("UPI ID is new for this user")

    hour = int(event_time.hour)
    if hour < 6 or hour >= 22:
        score += 12
        reasons.append("Transaction time falls in the user's higher-risk night window")

    if most_active_hour is not None and abs(hour - int(most_active_hour)) >= 8:
        score += 8
        reasons.append("Transaction time is far from the user's most active payment hour")

    daily_velocity = _projected_daily_velocity(history, event_time)
    comparison["projected_daily_transactions"] = daily_velocity
    if avg_daily_transactions > 0 and daily_velocity > max(avg_daily_transactions * 3, avg_daily_transactions + 6):
        score += 18
        reasons.append("Transaction velocity is unusually high compared with the user's normal daily activity")

    failed_transactions = int(profile.get("failed_transactions", 0) or 0)
    total_transactions = int(profile.get("transaction_count", 0) or 0)
    if total_transactions > 0 and (failed_transactions / total_transactions) > 0.2:
        score += 5
        reasons.append("Historical statement profile already contains a high failed transaction ratio")

    score = min(99, round(score))

    if not reasons:
        reasons.append("Payment fits the user's historical amount, merchant, and timing patterns")

    return {
        "risk_score": int(score),
        "risk_level": _level_from_score(score),
        "reasons": reasons,
        "comparison": comparison,
        "profile_available": True,
        "timestamp": event_time.isoformat(),
        "merchant": merchant,
        "location": location,
    }


def _projected_daily_velocity(history: pd.DataFrame, event_time: pd.Timestamp) -> int:
    if history.empty or "timestamp" not in history.columns:
        return 1

    history = history.copy()
    history["timestamp"] = pd.to_datetime(history["timestamp"], errors="coerce")
    same_day = history["timestamp"].dt.date == event_time.date()
    return int(same_day.sum()) + 1


def _level_from_score(score: float) -> str:
    if score >= 80:
        return "HIGH"
    if score >= 50:
        return "MEDIUM"
    return "LOW"
