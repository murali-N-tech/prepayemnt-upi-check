"""Loads the trained risk model.

The model is deliberately NOT committed to git: a pickle is tied to the
numpy/scikit-learn versions that produced it, so a checked-in one breaks on
any machine with different versions. It is regenerated locally instead:

    python backend/train_model.py

This module's job is to make that obvious when it has not been done, rather
than surfacing a pickle traceback that says nothing about the fix.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "models" / "risk_model.pkl"
METRICS_PATH = ROOT / "models" / "metrics.json"

TRAIN_COMMAND = "python backend/train_model.py"


def _installed_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("numpy", "scikit-learn", "scipy", "joblib"):
        try:
            module = __import__("sklearn" if name == "scikit-learn" else name)
            versions[name] = getattr(module, "__version__", "unknown")
        except ImportError:
            versions[name] = "not installed"
    return versions


def _version_mismatch_note() -> str:
    """Compare what is installed against what the model was trained with."""
    trained = load_metrics().get("environment") or {}
    if not trained:
        return ""
    installed = _installed_versions()
    differences = [
        f"      {pkg:14} trained with {trained[pkg]}, installed {installed.get(pkg)}"
        for pkg in trained
        if pkg in installed and trained[pkg] != installed[pkg]
    ]
    if not differences:
        return ""
    return "\n\n    Version differences found:\n" + "\n".join(differences)


def load_model():
    if not MODEL_PATH.exists():
        raise RuntimeError(
            f"No trained model at {MODEL_PATH.relative_to(ROOT)}.\n\n"
            f"    Train it:  {TRAIN_COMMAND}\n\n"
            "    Model files are not committed to git because a pickle is tied to\n"
            "    the library versions that produced it."
        )
    try:
        return joblib.load(MODEL_PATH)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load {MODEL_PATH.relative_to(ROOT)}: {exc}\n\n"
            "    This almost always means the file was produced by different\n"
            "    versions of numpy or scikit-learn than the ones installed here.\n"
            "    A pickle is not portable across those versions.\n\n"
            f"    Regenerate it:  {TRAIN_COMMAND}"
            + _version_mismatch_note()
        ) from exc


def load_metrics() -> dict[str, Any]:
    """The model's measured performance, so the API can report what it is
    rather than leaving the caller to assume."""
    if not METRICS_PATH.exists():
        return {}
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
