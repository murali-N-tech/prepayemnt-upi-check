"""The one place a risk score becomes a verdict.

APPROVE / WARN / STEP_UP / BLOCK is the system's only risk-band vocabulary,
and this module is its only definition. It lives in core rather than in
payee_check because both sides of the assembly need it: payee_check decides the
payment, and personalized_risk_service reports one family's own band, and a
module-level import in that direction would be a cycle. The cycle is why the
ladder was copied out in the first place - two bodies of if-statements with the
same thresholds, either of which could be edited alone.

The thresholds are policy, deliberately named so a reviewer can argue with
them, and they are unchanged: they are the numbers the report quotes and the
evaluation measures.

What does NOT belong here: the hard-block set. A malformed VPA or a blocked
payee is a BLOCK whatever the arithmetic says, and that override is about
findings rather than about scores, so it stays in payee_check with the rest of
the policy that reads findings.
"""

from __future__ import annotations

# Decision thresholds. Policy, not a model output.
BLOCK_AT = 70
STEP_UP_AT = 45
WARN_AT = 22

# In order of severity. Callers that rank verdicts (a test asserting evidence
# can only raise a verdict, a UI sorting rows) index into this rather than
# writing the order out again.
VERDICTS: tuple[str, ...] = ("APPROVE", "WARN", "STEP_UP", "BLOCK")


def verdict_from_score(score: float) -> str:
    """The canonical mapping. Every band in the system comes from here."""
    if score >= BLOCK_AT:
        return "BLOCK"
    if score >= STEP_UP_AT:
        return "STEP_UP"
    if score >= WARN_AT:
        return "WARN"
    return "APPROVE"


# The legacy LOW / MEDIUM / HIGH labels, expressed as a function of the
# canonical band rather than of the score.
#
# They used to be their own ladder at 80 and 50, which is how a score of 75
# could be published as BLOCK and MEDIUM in the same response - the two
# vocabularies were computed independently from the same number and nothing
# made them agree. Derived, they cannot disagree: a payment is HIGH exactly
# when it is a BLOCK.
_LEVEL_FOR = {"BLOCK": "HIGH", "STEP_UP": "MEDIUM", "WARN": "LOW", "APPROVE": "LOW"}


def level_from_verdict(verdict: str) -> str:
    """LOW / MEDIUM / HIGH for the callers that still render it."""
    return _LEVEL_FOR[verdict]


def level_from_score(score: float) -> str:
    """Convenience for the same thing from a raw score, via the canonical band."""
    return level_from_verdict(verdict_from_score(score))
