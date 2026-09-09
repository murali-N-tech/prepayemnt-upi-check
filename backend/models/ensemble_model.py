"""Loads the trained risk model.

This used to hand-roll an "ensemble" that averaged a LogisticRegression
probability with an IsolationForest's +1/-1 output mapped to 0.8/0.2, over
models fitted on random numbers. The weighting was arbitrary and the inputs
carried no signal.

The model is now a calibrated classifier trained and evaluated by
backend/train_model.py, which writes models/metrics.json alongside it. If the
file is missing, this raises with the command that produces it rather than
silently loading something stale.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "models" / "risk_model.pkl"
METRICS_PATH = ROOT / "models" / "metrics.json"


def load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"{MODEL_PATH} is missing. Train it with:  python backend/train_model.py"
        )
    return joblib.load(MODEL_PATH)


def load_metrics() -> dict[str, Any]:
    """The model's measured performance, so the API can report what it is
    rather than leaving the caller to assume."""
    if not METRICS_PATH.exists():
        return {}
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
