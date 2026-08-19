from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd
import numpy as np

from backend.pipeline.feature_store import FeatureStore

_feature_store_instance = FeatureStore()

def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def _geocode(location: str) -> tuple[float, float] | None:
    if not location:
        return None
    loc = location.lower()
    cities = {
        "mumbai": (19.0760, 72.8777),
        "delhi": (28.7041, 77.1025),
        "bangalore": (12.9716, 77.5946),
        "hyderabad": (17.3850, 78.4867),
        "chennai": (13.0827, 80.2707),
        "kolkata": (22.5726, 88.3639),
        "pune": (18.5204, 73.8567),
        "ahmedabad": (23.0225, 72.5714),
        "jaipur": (26.9124, 75.7873),
    }
    for city, coords in cities.items():
        if city in loc:
            return coords
    return None

def _compute_merchant_trust_score(merchant: str, history_df: pd.DataFrame, profile: dict[str, Any]) -> int:
    merchant_key = merchant.strip()
    mf = profile.get("merchant_frequency", {})
    frequency = mf.get(merchant_key, 0)

    if frequency == 0 and not history_df.empty:
        frequency = int((history_df["merchant"].astype(str) == merchant_key).sum())

    if frequency == 0:
        return 0

    merchant_txs = history_df[history_df["merchant"].astype(str) == merchant_key]

    success_rate = 1.0
    if not merchant_txs.empty and "status" in merchant_txs.columns:
        total = len(merchant_txs)
        successes = len(merchant_txs[merchant_txs["status"].str.upper() == "SUCCESS"])
        success_rate = successes / total if total > 0 else 1.0

    days_known = 0
    if not merchant_txs.empty and "timestamp" in merchant_txs.columns:
        merchant_txs = merchant_txs.copy()
        merchant_txs["timestamp"] = pd.to_datetime(merchant_txs["timestamp"], errors="coerce")
        valid_ts = merchant_txs["timestamp"].dropna()
        if not valid_ts.empty:
            first_txn = valid_ts.min()
            # fallback for naive/timezone aware
            utc_now = pd.Timestamp.utcnow()
            if first_txn.tzinfo is None:
                 utc_now = pd.Timestamp.utcnow().tz_localize(None)
            days_known = max(0, (utc_now - first_txn).days)

    frequency_score = min(40, frequency * 5)
    success_score = min(30, success_rate * 30)
    age_score = min(30, days_known / 10)

    return int(min(100, frequency_score + success_score + age_score))

def _compute_beneficiary_relationship(merchant: str, history_df: pd.DataFrame) -> dict[str, Any]:
    merchant_key = merchant.strip()
    if history_df.empty:
        return {"strength": 0, "txn_count": 0, "avg_amount": None}

    merchant_txs = history_df[history_df["merchant"].astype(str) == merchant_key]
    txn_count = len(merchant_txs)

    if txn_count == 0:
        return {"strength": 0, "txn_count": 0, "avg_amount": None}

    total_transferred = float(merchant_txs["amount"].sum())
    avg_amount = float(merchant_txs["amount"].mean())

    days_known = 0
    if "timestamp" in merchant_txs.columns:
        merchant_txs = merchant_txs.copy()
        merchant_txs["timestamp"] = pd.to_datetime(merchant_txs["timestamp"], errors="coerce")
        valid_ts = merchant_txs["timestamp"].dropna()
        if not valid_ts.empty:
            utc_now = pd.Timestamp.utcnow()
            if valid_ts.min().tzinfo is None:
                 utc_now = pd.Timestamp.utcnow().tz_localize(None)
            days_known = max(0, (utc_now - valid_ts.min()).days)

    consistency_bonus = 20 if txn_count >= 3 else 0
    strength = min(100, txn_count * 8 + days_known * 0.1 + consistency_bonus)

    return {
        "strength": int(strength),
        "txn_count": txn_count,
        "avg_amount": avg_amount
    }

def _compute_travel_speed(current_location: str | None, current_time: pd.Timestamp, history_df: pd.DataFrame) -> dict[str, Any]:
    if not current_location or history_df.empty or "location" not in history_df.columns:
        return {}

    current_coords = _geocode(current_location)
    if not current_coords:
        return {}

    history_with_loc = history_df[history_df["location"].notna() & (history_df["location"] != "")].copy()
    if history_with_loc.empty:
        return {}

    history_with_loc["timestamp"] = pd.to_datetime(history_with_loc["timestamp"], errors="coerce")
    history_with_loc = history_with_loc.dropna(subset=["timestamp"]).sort_values("timestamp")

    if history_with_loc.empty:
        return {}

    prev_tx = history_with_loc.iloc[-1]
    prev_loc_str = prev_tx["location"]
    prev_coords = _geocode(prev_loc_str)

    if not prev_coords:
        return {}

    distance_km = _haversine_distance(prev_coords[0], prev_coords[1], current_coords[0], current_coords[1])
    time_diff_hours = max(0.1, (current_time - prev_tx["timestamp"]).total_seconds() / 3600.0)
    speed_kmh = distance_km / time_diff_hours

    return {
        "speed_kmh": int(speed_kmh),
        "prev_location": prev_loc_str,
        "distance_km": int(distance_km),
        "time_diff_hours": round(time_diff_hours, 1)
    }

def _detect_sequence_anomaly(merchant: str, history_df: pd.DataFrame) -> bool:
    if history_df.empty or len(history_df) < 5:
        return False

    merchants = history_df["merchant"].astype(str).tolist()
    top_merchants = pd.Series(merchants).value_counts().head(10).index.tolist()

    if merchant in top_merchants:
        return False

    last_3 = merchants[-3:]
    all_in_top = all(m in top_merchants for m in last_3)

    return all_in_top

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

    # User_id is needed for caching features
    user_id = profile.get("user_id") if profile else None

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

    # Use feature store
    try:
        cached_features = _feature_store_instance.load_user_features(user_id) if user_id else None
    except Exception:
        cached_features = None

    avg_amount = float(profile.get("avg_amount", 0) or 0)
    max_amount = float(profile.get("max_amount", 0) or 0)
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

    merchant_trust = _compute_merchant_trust_score(merchant, history, profile)
    comparison["merchant_trust_score"] = merchant_trust
    if merchant_trust < 20:
        score += 20
        reasons.append(f"Merchant '{merchant}' has very low trust score ({merchant_trust}/100) - no established payment history")
    elif merchant_trust < 50:
        score += 10
        reasons.append(f"Merchant '{merchant}' trust score is below average ({merchant_trust}/100)")
    elif merchant_trust >= 80:
        score = max(5, score - 5)

    beneficiary = _compute_beneficiary_relationship(merchant, history)
    comparison["beneficiary_relationship_score"] = beneficiary["strength"]
    comparison["txn_count_with_payee"] = beneficiary["txn_count"]
    if beneficiary["avg_amount"] is not None:
        comparison["avg_amount_to_payee"] = beneficiary["avg_amount"]

    rel_strength = beneficiary["strength"]
    if rel_strength == 0:
        score += 15
        reasons.append(f"First-time beneficiary - no prior payment relationship found (trust: 0/100)")
    elif rel_strength < 30:
        score += 8
        reasons.append(f"Weak relationship with this beneficiary (score {rel_strength}/100)")
    elif rel_strength >= 70:
        score = max(5, score - 5)

    if beneficiary["avg_amount"] is not None and amount > 3 * beneficiary["avg_amount"] and beneficiary["txn_count"] > 0:
        score += 10
        reasons.append(f"Amount Rs.{amount} is >3x higher than typical payments to this beneficiary (Avg: Rs.{beneficiary['avg_amount']:.0f})")

    # Dynamic Check
    if not history.empty and "amount" in history.columns:
        amounts = pd.to_numeric(history["amount"], errors="coerce").dropna()
        if len(amounts) > 0:
            median_amt = amounts.median()
            mad_amt = (amounts - median_amt).abs().median()
            if mad_amt == 0:
                mad_amt = median_amt * 0.2

            low_thresh = median_amt + 2 * mad_amt
            med_thresh = median_amt + 4 * mad_amt
            high_thresh = median_amt + 6 * mad_amt

            comparison["median_amount"] = float(median_amt)
            comparison["amount_mad"] = float(mad_amt)
            comparison["threshold_low"] = float(low_thresh)
            comparison["threshold_medium"] = float(med_thresh)
            comparison["threshold_high"] = float(high_thresh)

            if amount > high_thresh:
                score += 35
                reasons.append(f"Amount Rs.{amount} exceeds statistical high threshold (Rs.{int(high_thresh)}) - beyond 6 MAD from median Rs.{int(median_amt)}")
            elif amount > med_thresh:
                score += 24
                reasons.append(f"Amount Rs.{amount} exceeds medium threshold (Rs.{int(med_thresh)}) - beyond 4 MAD from median Rs.{int(median_amt)}")
            elif amount > low_thresh:
                score += 12
                reasons.append(f"Amount Rs.{amount} exceeds low anomaly threshold (Rs.{int(low_thresh)})")

    if avg_amount > 0:
        amount_multiple = round(amount / avg_amount, 2)
        comparison["amount_multiple"] = amount_multiple

    if max_amount > 0 and amount > max_amount:
        score += 15
        reasons.append(f"Amount is higher than any previously seen transaction in history (Max: Rs.{max_amount})")

    if upi_id and upi_id not in known_upi_ids:
        score += 12
        reasons.append(f"UPI ID '{upi_id}' is new for this user")

    hour = int(event_time.hour)
    if hour < 6 or hour >= 22:
        score += 12
        reasons.append(f"Transaction time ({hour}:00) falls in the user's higher-risk night window")

    if most_active_hour is not None:
        diff = abs(hour - int(most_active_hour))
        wrap_diff = min(diff, 24 - diff)
        if wrap_diff >= 8:
            score += 8
            reasons.append(f"Transaction time ({hour}:00) is far from the user's most active payment hour ({most_active_hour}:00)")

    daily_velocity = _projected_daily_velocity(history, event_time)
    comparison["projected_daily_transactions"] = daily_velocity
    if avg_daily_transactions > 0 and daily_velocity > max(avg_daily_transactions * 3, avg_daily_transactions + 6):
        score += 18
        reasons.append(f"Transaction velocity: {daily_velocity} projected today vs daily average of {avg_daily_transactions:.1f} - velocity anomaly")

    failed_transactions = int(profile.get("failed_transactions", 0) or 0)
    total_transactions = int(profile.get("transaction_count", 0) or 0)
    if total_transactions > 0 and (failed_transactions / total_transactions) > 0.2:
        score += 5
        reasons.append("Historical statement profile contains a high failed transaction ratio")

    geo_data = _compute_travel_speed(location, event_time, history)
    if geo_data:
        comparison.update(geo_data)
        speed = geo_data["speed_kmh"]
        if speed > 1000:
            score += 25
            reasons.append(f"Impossible travel speed {speed} km/h detected between {geo_data['prev_location']} and {location} in {geo_data['time_diff_hours']}h")
        elif speed > 500:
            score += 15
            reasons.append(f"Suspicious travel speed {speed} km/h from {geo_data['prev_location']}")

    seq_anomaly = _detect_sequence_anomaly(merchant, history)
    comparison["sequence_anomaly"] = seq_anomaly
    if seq_anomaly:
        score += 8
        reasons.append(f"Transaction breaks the user's typical merchant sequence pattern")

    if user_id:
        try:
            _feature_store_instance.save_user_features(user_id, comparison)
        except Exception:
            pass

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
