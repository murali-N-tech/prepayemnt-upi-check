"""Behavioural signal from the two per-transaction scores.

The previous implementation was:

    score = np.mean([velocity, device_score])

which averages a transaction COUNT (roughly 1-15) with a 0-1 score. Velocity
dominates the mean by an order of magnitude, so velocity 2 with a perfectly
ordinary device score of 0.5 gives 1.25 and lands in "High Risk". Almost every
transaction came back High Risk, which makes the signal useless in both
directions: it never distinguishes anything, and it trains whoever reads it to
ignore the field.

Both inputs are put on the same 0-1 scale before they are combined, and the
weighting is stated rather than implied by an average.

DIRECTION OF device_score
-------------------------
It is a RISK score: 0 means a device the payer has used before, 1 means an
unrecognised one. This module adds it to risk, and /transactions produces it
from the risk score, so that is the codebase's operative definition - but this
docstring used to call it a "TRUST SCORE" and the slider in FraudDetection.tsx
was labelled "Device Trust Score", which is the opposite. Anyone reading either
one would have set the slider to 1.0 to mean "this is my own phone" and pushed
the behavioural risk up by 0.4 instead of down. The label is fixed; this note
exists so the ambiguity does not come back.
"""

from __future__ import annotations

# Above this many payments in the window, velocity is treated as maxed out.
# Beyond it the difference between 15 and 40 does not change the decision.
VELOCITY_CAP = 15.0

# Velocity is the stronger of the two signals: a burst is behaviour, whereas a
# device score is an assertion by whatever produced it.
VELOCITY_WEIGHT = 0.6
DEVICE_WEIGHT = 0.4

HIGH_RISK_AT = 0.70
MEDIUM_RISK_AT = 0.45


def normalised_velocity(velocity: float) -> float:
    """Map a payment count onto 0-1 so it can be combined with a trust score."""
    try:
        value = float(velocity)
    except (TypeError, ValueError):
        return 0.0
    return min(max(value, 0.0), VELOCITY_CAP) / VELOCITY_CAP


def behaviour_risk(velocity: float, device_score: float) -> float:
    """Combined 0-1 behavioural risk."""
    try:
        device = float(device_score)
    except (TypeError, ValueError):
        device = 0.0
    device = min(max(device, 0.0), 1.0)
    return VELOCITY_WEIGHT * normalised_velocity(velocity) + DEVICE_WEIGHT * device


def behavior_score(velocity, device_score) -> str:
    """Label for the /behavior endpoint. Name kept for existing callers."""
    score = behaviour_risk(velocity, device_score)
    if score >= HIGH_RISK_AT:
        return "High Risk"
    if score >= MEDIUM_RISK_AT:
        return "Medium Risk"
    return "Normal"
