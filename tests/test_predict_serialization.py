"""Publishing a feature vector that can legitimately hold NaN.

NaN means "not measurable" everywhere inside this system - that is the whole
basis of the evidence-availability work - and JSON has no way to write it. So
POST /predict, which echoes the vector it scored, returned 500 for every
payment to an address the reputation store had never seen. The commonest case
there is, failing on the one class of payee the system exists to warn about.

The fix is at the boundary and only there: the vector handed to the model is
untouched, and the vector handed to the client says null where the pipeline
says NaN. These tests hold both halves of that in place - the response is
always valid JSON, and the internal representation is still NaN.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from starlette.responses import JSONResponse

from backend.app.core.json_safe import json_safe
from backend.ml.features import build_features

UNKNOWN_PAYEE = "stranger.payee.7781@ybl"
KNOWN_PAYEE = "srilakshmi.canteen@ybl"
PAYMENT = {
    "amount": 2_500.0, "device_score": 0.2, "location_score": 0.1,
    "velocity_score": 0.3, "sender": "murali@okaxis",
    "timestamp": "2026-09-17T13:20:00",
}


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """An authenticated client over a throwaway database."""
    from fastapi.testclient import TestClient
    from backend.app.services import profile_store

    monkeypatch.setattr(profile_store, "DB_PATH", tmp_path / "predict.db")
    profile_store._SCHEMA_DONE.clear()
    import backend.main as main

    client = TestClient(main.app)
    registered = client.post(
        "/auth/register", json={"username": "murali@okaxis", "password": "hunter2hunter2"}
    )
    assert registered.status_code == 200, registered.text
    client.headers.update({"Authorization": f"Bearer {registered.json()['token']}"})
    try:
        yield client
    finally:
        profile_store._SCHEMA_DONE.clear()


def seed_payee_history(vpa: str, payers: int = 12) -> None:
    """Enough distinct payers, far enough back, for the payee row to be read."""
    from backend.app.services.payee_reputation import record_payment

    for n in range(payers):
        record_payment(vpa, payer_id=f"payer{n}@okaxis", amount=200.0 + n,
                       at="2024-03-01T12:00:00", display_name="SRI LAKSHMI CANTEEN")
        record_payment(vpa, payer_id=f"payer{n}@okaxis", amount=240.0 + n,
                       at="2026-09-10T12:00:00", display_name="SRI LAKSHMI CANTEEN")


def no_non_finite_tokens(response) -> None:
    """JSON has no NaN, no Infinity. A strict parser must accept the body."""
    for token in ("NaN", "Infinity", "-Infinity"):
        assert token not in response.text, f"{token} in the response body"

    def reject(literal):
        raise AssertionError(f"non-finite literal {literal} in the response")

    json.loads(response.text, parse_constant=reject)


# ── 1 and 2. Both payee states return valid JSON ─────────────────────────────

def test_a_payment_to_a_known_payee_serialises(api):
    seed_payee_history(KNOWN_PAYEE)
    r = api.post("/predict", json={**PAYMENT, "receiver": KNOWN_PAYEE})
    assert r.status_code == 200, r.text
    no_non_finite_tokens(r)
    assert r.json()["features"]["payee_history_available"] == 1.0


def test_a_payment_to_an_unknown_payee_no_longer_returns_500(api):
    """The regression. Before the fix this raised
    ValueError: Out of range float values are not JSON compliant
    inside the response renderer, which FastAPI reports as a 500."""
    r = api.post("/predict", json={**PAYMENT, "receiver": UNKNOWN_PAYEE})
    assert r.status_code == 200, r.text
    no_non_finite_tokens(r)


# ── 3. No non-finite value anywhere in the response ──────────────────────────

@pytest.mark.parametrize("receiver", [UNKNOWN_PAYEE, "another.stranger@fastpay"])
def test_no_response_value_is_non_finite(api, receiver):
    r = api.post("/predict", json={**PAYMENT, "receiver": receiver})
    assert r.status_code == 200, r.text

    def walk(value, path="$"):
        if isinstance(value, float):
            assert math.isfinite(value), f"{path} is {value}"
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for n, item in enumerate(value):
                walk(item, f"{path}[{n}]")

    walk(r.json())


def test_a_large_night_payment_to_a_stranger_also_serialises(api):
    """The shape of payment this endpoint is most likely to be asked about."""
    r = api.post("/predict", json={**PAYMENT, "receiver": UNKNOWN_PAYEE,
                                   "amount": 84_000.0,
                                   "timestamp": "2026-09-17T02:30:00"})
    assert r.status_code == 200, r.text
    no_non_finite_tokens(r)


# ── 4. The numbers are the same numbers ──────────────────────────────────────

def test_the_published_score_is_the_model_reading_of_the_published_vector(api):
    """Serialising for the wire must not change what was scored.

    The response's own vector is fed back through the model, with null read as
    NaN again. If the conversion had altered a value - most plausibly by writing
    0 where the pipeline held NaN - the probability would move, because that is
    exactly the substitution the model is trained to distinguish.
    """
    import backend.main as main
    from backend.ml.dataset import FEATURES

    r = api.post("/predict", json={**PAYMENT, "receiver": UNKNOWN_PAYEE})
    assert r.status_code == 200, r.text
    body = r.json()

    published = body["features"]
    assert any(value is None for value in published.values()), (
        "this case is only interesting while something really was unavailable"
    )
    row = pd.DataFrame(
        [[np.nan if published[name] is None else float(published[name]) for name in FEATURES]],
        columns=list(FEATURES),
    )
    probability = float(main.model_or_503().predict_proba(row)[0][1])
    assert body["probability"] == pytest.approx(round(probability, 5))
    assert body["risk_score"] == int(round(probability * 100))
    assert body["risk"] in (0, 1)
    assert body["threshold"] == pytest.approx(round(main.DECISION_THRESHOLD, 5))


def test_the_payee_check_verdict_and_confidence_are_untouched(api):
    """The assembled assessment has its own boundary and its own vocabulary;
    this change must not have reached either."""
    from backend.app.services.payee_check import check_payee

    result = check_payee(payload=UNKNOWN_PAYEE, payer_id="murali@okaxis", amount=2_500.0,
                         profile=None, history=pd.DataFrame(),
                         timestamp="2026-09-17T13:20:00")
    assert result["verdict"] in {"APPROVE", "WARN", "STEP_UP", "BLOCK"}
    assert isinstance(result["risk_score"], int)
    assert isinstance(result["confidence_score"], int)
    assert "payer_behaviour" in result["missing_evidence"]
    assert "ml_classifier" in result["missing_evidence"]
    for row in result["evidence"]:
        if not row["available"]:
            assert row["score"] is None, "unavailable evidence still carries no score"


# ── 5. Unavailable stays distinguishable from measured ───────────────────────

def test_an_unavailable_payee_feature_is_null_and_a_measured_one_is_a_number(api):
    unknown = api.post("/predict", json={**PAYMENT, "receiver": UNKNOWN_PAYEE}).json()
    seed_payee_history(KNOWN_PAYEE)
    known = api.post("/predict", json={**PAYMENT, "receiver": KNOWN_PAYEE}).json()

    for name in ("payee_age_days", "payee_distinct_payers", "payee_repeat_ratio"):
        assert unknown["features"][name] is None, f"{name} should be null when unread"
        assert isinstance(known["features"][name], (int, float)), name

    # The companion flag is the explicit answer, and it is not a float that
    # could be mistaken for a measurement of the payee itself.
    assert unknown["features"]["payee_history_available"] == 0.0
    assert known["features"]["payee_history_available"] == 1.0


def test_null_is_not_confused_with_a_measured_zero(api):
    """0.0 means "we looked, and the answer is none". null means "we could not
    look". Collapsing those is the failure the availability work exists to
    prevent, and a serialiser that wrote 0 instead of null would reintroduce it.
    """
    unknown = api.post("/predict", json={**PAYMENT, "receiver": UNKNOWN_PAYEE}).json()
    assert unknown["features"]["payee_age_days"] is not 0  # noqa: F632 - identity is the point
    assert unknown["features"]["payee_age_days"] is None
    assert unknown["features"]["is_night"] == 0.0, "a measured zero is still a zero"


def test_the_internal_vector_still_carries_nan(api):
    """The representation the model reads is unchanged. If this ever fails, the
    fix has leaked inwards from the boundary."""
    from backend.app.services.payee_check import payee_key
    from backend.app.services.payee_reputation import assess_payee

    payee = assess_payee(payee_key(UNKNOWN_PAYEE, UNKNOWN_PAYEE))
    features = build_features(
        amount=2_500.0, timestamp=PAYMENT["timestamp"], profile=None,
        reputation=payee.as_dict(), seconds_since_last_txn=3600.0,
        txns_last_hour=0.0, txns_today=0.0, payer_seen_payee_before=False,
    )
    for name in ("payee_age_days", "payee_distinct_payers", "payee_repeat_ratio"):
        assert math.isnan(features[name]), f"{name} should still be NaN internally"


# ── 6. Nothing global changed ────────────────────────────────────────────────

def test_the_default_response_class_still_rejects_non_finite_floats():
    """The fix is a conversion at one boundary, not a permissive encoder. If
    JSONResponse ever starts writing bare NaN, every other response in the app
    silently becomes non-standard JSON."""
    with pytest.raises(ValueError):
        JSONResponse(content={"x": float("nan")})
    with pytest.raises(ValueError):
        JSONResponse(content={"x": float("inf")})


def test_the_app_has_not_swapped_its_response_class():
    import backend.main as main

    default = main.app.router.default_response_class
    # FastAPI wraps an unset response class in a DefaultPlaceholder.
    assert getattr(default, "value", default) is JSONResponse


def test_the_standard_library_encoder_is_untouched():
    assert json.dumps(float("nan")) == "NaN", "stdlib default, unmodified"
    with pytest.raises(ValueError):
        json.dumps(float("nan"), allow_nan=False)


# ── The helper itself ────────────────────────────────────────────────────────

def test_json_safe_converts_only_non_finite_floats():
    assert json_safe(float("nan")) is None
    assert json_safe(float("inf")) is None
    assert json_safe(float("-inf")) is None
    assert json_safe(np.float64("nan")) is None
    assert json_safe(0.0) == 0.0
    assert json_safe(-1.5) == -1.5
    assert json_safe(np.float64(2.5)) == 2.5
    assert json_safe(7) == 7 and isinstance(json_safe(7), int)
    assert json_safe("NaN") == "NaN", "a string that says NaN is a string"
    assert json_safe(None) is None
    assert json_safe(True) is True


def test_json_safe_reaches_nested_values():
    payload = {"a": [1.0, float("nan"), {"b": float("-inf")}], "c": (float("nan"), 2)}
    assert json_safe(payload) == {"a": [1.0, None, {"b": None}], "c": [None, 2]}


def test_json_safe_output_is_always_serialisable():
    payload = {"features": {"x": float("nan"), "y": np.float64("inf"), "z": 3.0}}
    assert json.dumps(json_safe(payload), allow_nan=False)
