"""The evidence layer: risk and confidence must move independently.

The property under test is that "nothing found" and "nothing checked" produce
different results. Everything else here is guarding the arithmetic that was
already argued for in the report - damped-max, one vote per family, monotone -
against the change that introduced availability.
"""

from __future__ import annotations

import pytest

from backend.app.core.entity_status import EvidenceLevel
from backend.app.services.evidence import (
    CONFIDENCE_WEIGHT,
    Fact,
    Assessment,
    Evidence,
    Family,
    agreement_bonus,
    assess,
    combine_scores,
    confidence_score,
    evidence_level,
    unavailable,
)


# One distinct fact per family, so each row is an independent observation and
# the bonus behaves the way it did when it counted families. Families that
# genuinely share a fact are tested separately in test_fact_corroboration.py.
_FACT_FOR = dict(zip(Family, Fact))


def clean(family: Family) -> Evidence:
    return Evidence(family=family, available=True, score=0, severity="info")


def scored(family: Family, score: int, severity: str = "warn") -> Evidence:
    return Evidence(family=family, available=True, score=score, severity=severity,
                    code=f"{family.value}_test", message="test finding",
                    facts=frozenset({_FACT_FOR[family]}))


def decide(score: int, findings) -> str:
    if score >= 70:
        return "BLOCK"
    if score >= 45:
        return "STEP_UP"
    if score >= 22:
        return "WARN"
    return "APPROVE"


ALL = list(Family)


# ── The central distinction ──────────────────────────────────────────────────

def test_nothing_found_and_nothing_checked_differ():
    """The reason this module exists.

    Both cases produce a low risk score. Only one of them is an all-clear, and
    a caller that cannot tell them apart will present a payment to an address
    nobody has ever seen exactly as it presents a payment to a two-year-old
    merchant with four hundred repeat customers.
    """
    everything_clean = assess([clean(f) for f in ALL], decide)
    nothing_known = assess(
        [clean(Family.ADDRESS), clean(Family.AMOUNT_CONTEXT)]
        + [unavailable(f, "no data") for f in ALL
           if f not in (Family.ADDRESS, Family.AMOUNT_CONTEXT)],
        decide,
    )

    assert everything_clean.risk == nothing_known.risk == 0
    assert everything_clean.verdict == nothing_known.verdict == "APPROVE"

    # Identical risk, and nothing else identical.
    assert everything_clean.confidence == 100
    assert nothing_known.confidence < 20
    assert everything_clean.level is EvidenceLevel.FULL
    assert nothing_known.level is EvidenceLevel.MINIMAL
    assert nothing_known.missing and not everything_clean.missing


def test_unavailable_evidence_cannot_carry_a_score():
    with pytest.raises(ValueError, match="contributes nothing"):
        Evidence(family=Family.PAYEE_HISTORY, available=False, score=40)


def test_unavailable_evidence_does_not_lower_risk():
    """Removing a clean family must not make the result look worse, and
    marking it unavailable must not make it look better."""
    suspicious = [scored(Family.MESSAGE_PRESSURE, 55, "high")]
    with_clean = assess(suspicious + [clean(Family.PAYEE_HISTORY)], decide)
    with_missing = assess(suspicious + [unavailable(Family.PAYEE_HISTORY, "unknown")], decide)
    assert with_clean.risk == with_missing.risk
    assert with_missing.confidence < with_clean.confidence


# ── Combination arithmetic, preserved ────────────────────────────────────────

def test_strongest_signal_leads_and_others_are_damped():
    assert combine_scores([60]) == 60
    assert combine_scores([60, 40]) == 76          # 60 + 0.4*40
    assert combine_scores([]) == 0
    assert combine_scores([0, 0]) == 0
    assert combine_scores([99, 99, 99]) == 99      # capped


def test_combination_is_monotonic():
    """Adding independent suspicious evidence must never reduce risk.

    Asserted across the whole family set rather than on an example, because
    the failure this guards against was a lookup table that ran out: a fifth
    agreeing family fell off the end of the bonus table and dropped the score
    from 22 to 0.
    """
    base: list[Evidence] = []
    previous = -1
    for family in ALL:
        base = base + [scored(family, 30)]
        risk = assess(base, decide).risk
        assert risk >= previous, f"risk fell to {risk} when {family.value} was added"
        previous = risk


def test_the_classifier_corroborates_only_on_facts_of_its_own():
    """It is no longer silenced outright - fact-aware corroboration handles
    the overlap properly. Declaring a fact another family already reported
    adds nothing; declaring one nothing else observes counts."""
    without = [scored(Family.PAYEE_HISTORY, 40), scored(Family.AMOUNT_CONTEXT, 30)]

    duplicate = without + [Evidence(family=Family.ML_CLASSIFIER, available=True, score=55,
                                    severity="high",
                                    facts=frozenset({_FACT_FOR[Family.PAYEE_HISTORY]}))]
    assert agreement_bonus(duplicate)[0] == agreement_bonus(without)[0]
    # Its score still reaches the total even when its vote adds nothing.
    assert assess(duplicate, decide).risk > assess(without, decide).risk

    distinct = without + [scored(Family.ML_CLASSIFIER, 55)]
    assert agreement_bonus(distinct)[0] > agreement_bonus(without)[0]


def test_one_vote_per_family():
    """Four findings inside one message are one agreeing stream, not four."""
    one_family = [Evidence(family=Family.MESSAGE_PRESSURE, available=True, score=40,
                           severity="high", findings=["a", "b", "c", "d"],
                           facts=frozenset({Fact.MESSAGE_COERCION}))]
    bonus, agreeing = agreement_bonus(one_family)
    assert bonus == 0 and agreeing == ["message_coercion"]

    two_families = one_family + [scored(Family.ADDRESS, 40)]
    bonus, agreeing = agreement_bonus(two_families)
    assert bonus == 6 and len(agreeing) == 2


def test_an_unavailable_family_casts_no_vote():
    votes = [scored(Family.ADDRESS, 40), unavailable(Family.PAYEE_HISTORY, "unknown")]
    bonus, agreeing = agreement_bonus(votes)
    assert bonus == 0, "a family that could not look must not count as agreeing"
    assert agreeing == [_FACT_FOR[Family.ADDRESS].value]


# ── Confidence and level ─────────────────────────────────────────────────────

def test_confidence_is_full_coverage_and_empty_coverage():
    assert confidence_score([clean(f) for f in ALL]) == 100
    assert confidence_score([unavailable(f, "x") for f in ALL]) == 0


def test_confidence_weights_the_families_that_actually_distinguish():
    """Losing the payee's history must cost more confidence than losing the
    stated purpose. Otherwise a fully-unknown payee reports as well-covered
    because the cheap, always-available families made up the number."""
    assert CONFIDENCE_WEIGHT[Family.PAYEE_HISTORY] > CONFIDENCE_WEIGHT[Family.ADDRESS]
    assert CONFIDENCE_WEIGHT[Family.RELATIONSHIP] > CONFIDENCE_WEIGHT[Family.STATED_PURPOSE]

    lost_history = [unavailable(Family.PAYEE_HISTORY, "x")] + \
                   [clean(f) for f in ALL if f is not Family.PAYEE_HISTORY]
    lost_purpose = [unavailable(Family.STATED_PURPOSE, "x")] + \
                   [clean(f) for f in ALL if f is not Family.STATED_PURPOSE]
    assert confidence_score(lost_history) < confidence_score(lost_purpose)


@pytest.mark.parametrize("present, expected", [
    ((Family.PAYEE_HISTORY, Family.PAYER_BEHAVIOUR, Family.RELATIONSHIP), EvidenceLevel.FULL),
    ((Family.PAYER_BEHAVIOUR,), EvidenceLevel.PARTIAL),
    ((Family.PAYEE_HISTORY,), EvidenceLevel.PARTIAL),
    ((Family.ADDRESS, Family.SCAM_LINKS), EvidenceLevel.MINIMAL),
    ((), EvidenceLevel.MINIMAL),
])
def test_evidence_level_reflects_the_core_families(present, expected):
    ev = [clean(f) if f in present else unavailable(f, "x") for f in ALL]
    assert evidence_level(ev) is expected


# ── Status must not decide the verdict ───────────────────────────────────────

def test_a_critical_finding_still_blocks_at_minimal_coverage():
    """An unknown payee with a malformed address is still blocked. Low
    confidence describes how much we know, and must not become a reason to
    withhold a verdict the evidence supports."""
    ev = [Evidence(family=Family.ADDRESS, available=True, score=70, severity="critical",
                   code="vpa_malformed")] + \
         [unavailable(f, "no data") for f in ALL if f is not Family.ADDRESS]
    result = assess(ev, decide)
    assert result.verdict == "BLOCK"
    assert result.level is EvidenceLevel.MINIMAL
    assert result.confidence < 20


def test_high_confidence_does_not_imply_low_risk():
    ev = [scored(f, 45, "high") for f in ALL]
    result = assess(ev, decide)
    assert result.confidence == 100
    assert result.verdict == "BLOCK"


def test_the_response_shape_matches_the_api_contract():
    result = assess(
        [scored(Family.ADDRESS, 30)] + [unavailable(f, "no data") for f in ALL
                                        if f is not Family.ADDRESS],
        decide,
    )
    payload = result.as_dict()
    assert set(payload) == {"risk", "evidence", "missing_evidence", "agreement"}
    assert set(payload["risk"]) == {"score", "confidence", "evidence_level", "verdict"}
    row = payload["evidence"][0]
    assert set(row) >= {"family", "available", "score", "severity", "code", "message"}
    # An unavailable family reports null rather than 0 - the same distinction
    # the feature pipeline makes, carried through to the wire.
    absent = next(e for e in payload["evidence"] if not e["available"])
    assert absent["score"] is None and absent["severity"] is None
    assert "payee_history" in payload["missing_evidence"]
