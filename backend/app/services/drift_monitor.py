"""Has the model's output distribution moved?

The previous version took the mean of the binary `risk` flag over the first
ten and last ten rows and called anything above 0.3 drift. Ten Bernoulli
samples have a standard error of about 0.16, so a gap of 0.3 is roughly two
standard errors: it fires on chance alone a few percent of the time, and -
worse in a fraud tool - it reported "Model Stable" with exactly the same
confidence when the data could not support either conclusion.

This version:

  - uses the continuous risk_score rather than the thresholded flag, so a
    drift that moves scores from 45 to 65 is visible instead of invisible,
  - splits whatever history exists in half instead of sampling 20 rows,
  - compares the observed gap against the sampling noise of that gap
    (Welch standard error) rather than a fixed 0.3,
  - and says "not enough data" when there genuinely is not enough, instead
    of defaulting to the reassuring answer.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

# Each half needs enough rows for its mean to mean anything. Below this the
# honest answer is that the question cannot be answered yet.
MIN_PER_WINDOW = 15

# How many standard errors apart the two window means must be. 2.0 is a
# two-sided test at roughly the 5% level - the point of naming it is that the
# threshold is now in units of noise, not in units of score.
DRIFT_SIGMAS = 2.0


def drift_report(old_scores: Sequence[float], new_scores: Sequence[float]) -> dict[str, Any]:
    """The numbers behind the verdict, so the UI can show the margin."""
    old = np.asarray([x for x in old_scores if x is not None], dtype=float)
    new = np.asarray([x for x in new_scores if x is not None], dtype=float)

    if old.size < MIN_PER_WINDOW or new.size < MIN_PER_WINDOW:
        return {
            "status": "Not enough data",
            "detail": (
                f"Needs at least {MIN_PER_WINDOW} scored payments in each half of "
                f"the history; have {old.size} and {new.size}."
            ),
            "conclusive": False,
        }

    gap = float(new.mean() - old.mean())
    # Welch: the two windows have no reason to share a variance.
    se = float(np.sqrt(old.var(ddof=1) / old.size + new.var(ddof=1) / new.size))
    if se == 0.0:
        # Every score identical in both windows. Identical means are stable;
        # different means with zero spread are a step change.
        sigmas = 0.0 if gap == 0.0 else float("inf")
    else:
        sigmas = abs(gap) / se

    drifted = sigmas >= DRIFT_SIGMAS
    return {
        "status": "Drift Detected" if drifted else "Model Stable",
        "detail": (
            f"Mean score moved {gap:+.1f} points "
            f"({old.mean():.1f} -> {new.mean():.1f}), "
            f"{sigmas:.1f}x the sampling noise of that gap "
            f"(drift called at {DRIFT_SIGMAS:.0f}x)."
        ),
        "conclusive": True,
        "mean_before": round(float(old.mean()), 2),
        "mean_after": round(float(new.mean()), 2),
        "shift": round(gap, 2),
        "sigmas": None if sigmas == float("inf") else round(sigmas, 2),
        "n_before": int(old.size),
        "n_after": int(new.size),
    }


def detect_drift(old_scores: Sequence[float], new_scores: Sequence[float]) -> str:
    """Verdict only, for callers that want the one-liner."""
    return drift_report(old_scores, new_scores)["status"]
