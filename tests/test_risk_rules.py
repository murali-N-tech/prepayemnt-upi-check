"""The personalized risk engine's scoring rules."""

from __future__ import annotations

import pandas as pd

from backend.app.services.personalized_risk_service import evaluate_personalized_risk

PROFILE = {
    "transaction_count": 200,
    "avg_amount": 500.0,
    "max_amount": 5000.0,
    "favorite_merchants": ["Swiggy", "Zomato"],
    "known_upi_ids": ["swiggy@ibl"],
    "most_active_hour": 13,
    "average_daily_transactions": 2.0,
    "failed_transactions": 0,
}
HISTORY = pd.DataFrame(
    [{"timestamp": "2026-06-01T13:00:00", "merchant": "Swiggy", "amount": 480.0}]
)


def test_a_familiar_payment_scores_low():
    r = evaluate_personalized_risk(
        profile=PROFILE, history=HISTORY, amount=450.0,
        merchant="Swiggy", timestamp="2026-06-02T13:10:00", upi_id="swiggy@ibl",
    )
    assert r["risk_level"] == "LOW"


def test_a_large_payment_to_an_unknown_payee_at_night_scores_high():
    r = evaluate_personalized_risk(
        profile=PROFILE, history=HISTORY, amount=75000.0,
        merchant="unknown-payee", timestamp="2026-06-02T23:30:00", upi_id="scam@ybl",
    )
    assert r["risk_level"] == "HIGH"
    assert any("average payment" in reason for reason in r["reasons"])


def test_no_profile_falls_back_to_a_baseline():
    r = evaluate_personalized_risk(
        profile=None, history=pd.DataFrame(), amount=20000.0,
        merchant="anyone", timestamp="2026-06-02T12:00:00",
    )
    assert r["profile_available"] is False
    assert 0 < r["risk_score"] < 100
