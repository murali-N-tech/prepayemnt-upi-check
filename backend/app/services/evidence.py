"""Evidence families, and the difference between low risk and no information.

The engine already scored independent evidence families and merged them with a
damped-max rule plus an agreement bonus. That arithmetic is preserved here
unchanged, for two reasons: it is argued for in the project report, and it is
the part that works. What is added is the thing it could not express.

The problem
-----------
A family that found nothing and a family that could not look both contributed
0 to the old combination, and 0 is indistinguishable from "clean". So a payee
nobody has ever seen scored the same as a payee with two years of good
history, and the result carried no way to tell the caller which it was looking
at. Every downstream consumer - the UI, the assistant, the user - read the
first as the second.

The fix is not to guess at the missing evidence. It is to report two numbers.

    risk        how bad the available evidence looks
    confidence  how much evidence there was to look at

A risk of 15 at a confidence of 94 is a well-supported all-clear. A risk of 18
at a confidence of 41 is a shrug. They are not the same result and must never
render the same way.

Why confidence is not just "risk with error bars"
-------------------------------------------------
It is deliberately computed from evidence COVERAGE and not from the model's
own probability. A calibrated classifier can be confidently wrong about a case
it has no features for; asking it how sure it is would return an answer built
from the same absent data. Coverage is a fact about the input, which is what a
user actually needs: "we could not check the payee's history" is actionable in
a way that "the posterior variance is elevated" is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.app.core.entity_status import EvidenceLevel



class Fact(str, Enum):
    """The underlying observations a family can rest its score on.

    Fact-aware corroboration exists to stop correlated evidence being counted
    as independent. The agreement bonus rewards separate observations pointing
    the same way; it is worth a lot precisely because independent streams
    rarely err together. Counting FAMILIES made that easy to fake - the
    classifier reads `is_night`, the payer rules read `hour < 6 or hour >= 22`,
    and those are character-for-character the same predicate over the same
    timestamp. Two modules, one observation, and the payment collected a bonus
    for the system having looked at the clock twice.

    So a family declares the facts its score rests on, and the bonus counts
    DISTINCT facts. Two families reporting `HOUR_ANOMALY` corroborate nothing;
    one reporting `HOUR_ANOMALY` and another `PAYEE_SHAPE` corroborate.

    Tags name evidence CONCEPTS, not individual rules. There is one
    AMOUNT_DEVIATION, not one per threshold band, and deliberately one even
    though the payer rules divide by the mean while the model divides by the
    median: a disagreement about which estimator to use is not a second
    observation of the world. (That split was audited and kept. A fixed
    threshold ladder and a learned function need denominators calibrated to
    themselves - see the long comment above the ladder in
    personalized_risk_service - so the two statistics coexist on purpose. One
    fact either way, which is what stops the payment collecting a
    corroboration bonus for its size being measured twice.)

    Use these members, never string literals, so that "payee_shape",
    "payee-shape" and "payee_history_shape" cannot become three concepts.
    """

    # Payer-relative
    AMOUNT_DEVIATION = "amount_deviation"      # size against this payer's own norm
    HOUR_ANOMALY = "hour_anomaly"              # night window AND distance from usual hour
    VELOCITY_DAILY = "velocity_daily"          # payments today against the daily norm
    VELOCITY_HOURLY = "velocity_hourly"        # burst inside the hour - a different signal
    PAYER_RELIABILITY = "payer_reliability"    # this payer's failed-payment history

    # Payee-relative
    PAYEE_SHAPE = "payee_shape"                # age, distinct payers, repeat ratio
    PAYEE_REPORTS = "payee_reports"            # what other users have reported
    PAYEE_FAMILIARITY = "payee_familiarity"    # has THIS payer paid this payee before
    GRAPH_POSITION = "graph_position"          # position in the payer-payee graph

    # Payload and context
    ADDRESS_INTEGRITY = "address_integrity"    # VPA structure, handle, confusables
    AMOUNT_ABSOLUTE = "amount_absolute"        # size against the rail, not the payer
    LINK_REPUTATION = "link_reputation"        # URLs carried alongside the payment
    STATED_PURPOSE = "stated_purpose"          # the purpose the payer gave
    MESSAGE_COERCION = "message_coercion"      # pressure in the wording


class Family(str, Enum):
    """The independent streams. Independence is the whole basis of the
    agreement bonus, so two families must not read the same underlying fact.

    The wire values match the keys check_payee already published, so the
    frontend contract does not churn for a rename.

    ADDRESS covers the address AND the payload it arrived in - the handle, the
    confusables, the display-name mismatch, the embedded url parameter. An
    earlier draft of this enum split those into two families. Both reasons for
    merging them matter. They are one scan of one payload, so two votes for
    them would be one observation counted twice. And separating them would
    change the arithmetic: they are summed inside total_weight today, whereas
    two families are combined with the second damped to 0.4, so the split
    would quietly move every score that carries both.
    """

    ADDRESS = "address_and_qr"              # VPA, handle, confusables, payload
    PAYEE_HISTORY = "payee_history"         # aggregate reputation and shape
    PAYER_BEHAVIOUR = "payer_behaviour"     # this payer against their own norm
    RELATIONSHIP = "relationship"           # this payer with this payee
    AMOUNT_CONTEXT = "amount_context"       # limits and amount plausibility
    STATED_PURPOSE = "stated_intent"        # what the payer says this is for
    MESSAGE_PRESSURE = "message_pressure"   # coercive framing in the message
    SCAM_LINKS = "link_safety"              # URLs carried in message or payload
    ML_CLASSIFIER = "ml_classifier"         # the calibrated behavioural model
    GRAPH = "graph"                         # position in the payer-payee graph


# Families that contribute score but cast no agreement vote.
#
# The bonus rewards independent streams corroborating one another. The
# classifier is not one: it reads the payer's amount, hour and velocity, which
# is what PAYER_BEHAVIOUR reads, and the payee's age, payer count and repeat
# ratio, which is what PAYEE_HISTORY reads. A vote from it would be the same
# evidence counted again under a different name, and a payment flagged by the
# reputation family alone would collect a two-family bonus for one observation.
#
# It still contributes to the score, and it can still be the reason a payment
# is stopped. It just cannot vouch for itself.
# Families that score but never corroborate, whatever they declare.
#
# The classifier used to be listed here, as the blunt fix for it re-reading
# what PAYER_BEHAVIOUR and PAYEE_HISTORY had already reported. Fact-aware
# corroboration handles that properly now - the model's overlapping facts
# collapse into the families that share them, while VELOCITY_HOURLY, which
# nothing else observes, still counts. Silencing it outright would throw that
# away, so it has been removed from this set.
#
# The mechanism stays. A family whose score is a re-derivation of others, with
# no fact of its own, belongs here.
NON_VOTING: frozenset[Family] = frozenset()


# What each family contributes to confidence when it is available. These are
# weights on EVIDENCE VALUE, not on risk: the question each answers is "how
# much less would we know without this?".
#
# Payee history and the relationship carry the most because they are the only
# families that can distinguish a stranger from a known-good counterparty, and
# that distinction is what the system is for. The address and QR families
# weigh less here despite being able to hard-block: they are nearly always
# available, so having them tells you little about how well-covered a case is.
CONFIDENCE_WEIGHT: dict[Family, float] = {
    Family.PAYEE_HISTORY: 24.0,
    Family.RELATIONSHIP: 18.0,
    Family.PAYER_BEHAVIOUR: 16.0,
    Family.ML_CLASSIFIER: 12.0,
    Family.GRAPH: 8.0,
    Family.ADDRESS: 11.0,
    Family.AMOUNT_CONTEXT: 5.0,
    Family.MESSAGE_PRESSURE: 3.0,
    Family.SCAM_LINKS: 2.0,
    Family.STATED_PURPOSE: 1.0,
}
_TOTAL_WEIGHT = sum(CONFIDENCE_WEIGHT.values())

# Families whose absence drops the whole assessment out of FULL coverage.
_CORE = (Family.PAYEE_HISTORY, Family.PAYER_BEHAVIOUR, Family.RELATIONSHIP)


@dataclass
class Evidence:
    """One family's contribution, including the case where it had nothing to
    work with. `available=False` is a first-class outcome, not an error."""

    family: Family
    available: bool
    score: int = 0
    severity: str = "info"
    code: str = ""
    message: str = ""
    unavailable_because: str = ""
    findings: list[Any] = field(default_factory=list)
    # The underlying observations this score rests on. A set, so a family that
    # raised four findings about the clock still declares HOUR_ANOMALY once.
    facts: frozenset[Fact] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        self.facts = frozenset(self.facts)
        bad = [f for f in self.facts if not isinstance(f, Fact)]
        if bad:
            raise ValueError(
                f"{self.family.value} declared {bad!r}; use the Fact enum so that "
                "two spellings of one concept cannot become two concepts"
            )
        if not self.available and self.facts:
            raise ValueError(
                f"{self.family.value} is unavailable but declares facts; a family "
                "that could not look has observed nothing"
            )
        if not self.available and self.score:
            # A family that could not look must not contribute risk. Allowing
            # it would make "we do not know" push the score in a direction,
            # which is the failure this module exists to prevent.
            raise ValueError(
                f"{self.family.value} is unavailable but carries score "
                f"{self.score}; unavailable evidence contributes nothing"
            )

    @property
    def counts_toward_agreement(self) -> bool:
        return self.available and self.score > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family.value,
            "available": self.available,
            "score": self.score if self.available else None,
            "severity": self.severity if self.available else None,
            "code": self.code or None,
            "message": self.message or None,
            "unavailable_because": self.unavailable_because or None,
            "facts": sorted(f.value for f in self.facts),
        }


def unavailable(family: Family, because: str) -> Evidence:
    return Evidence(family=family, available=False, unavailable_because=because)


# ── Combination ──────────────────────────────────────────────────────────────
# Preserved from payee_check._combine and _agreement_bonus. The only change is
# that unavailable families are not in the input at all, rather than entering
# as zeros.

AGREEMENT_BONUS = {2: 6, 3: 14, 4: 22, 5: 28, 6: 32}
_MAX_AGREEMENT_BONUS = max(AGREEMENT_BONUS.values())
AGREEMENT_THRESHOLD = 20


def combine_scores(scores: list[int]) -> int:
    """Strongest signal leads; the others add a damped amount.

    Straight addition saturates on any two moderate signals, and a plain max
    throws away corroboration. Monotonic by construction: every term is
    non-negative, so adding a further suspicious family can only raise the
    total or leave it unchanged.
    """
    ordered = sorted((s for s in scores if s), reverse=True)
    if not ordered:
        return 0
    total = ordered[0] + sum(s * 0.4 for s in ordered[1:])
    return int(min(99, round(total)))


def corroborating_facts(evidence: list[Evidence]) -> tuple[list[Fact], dict[str, list[str]]]:
    """The distinct observations supporting a flag, and who reported each.

    A fact participates only when the family reporting it is available, is not
    in NON_VOTING, and scored at or above the participation threshold. The
    threshold is what it always was: a family murmuring at 6 is not evidence
    that corroborates anything, whatever it read to get there.

    Returns the distinct facts and, for each, the families that observed it -
    so the response can say "two modules, one observation" rather than leaving
    the reader to infer why four flagging families earned no bonus.
    """
    by_fact: dict[Fact, list[str]] = {}
    for e in evidence:
        if not e.counts_toward_agreement:
            continue
        if e.score < AGREEMENT_THRESHOLD or e.family in NON_VOTING:
            continue
        for fact in e.facts:
            by_fact.setdefault(fact, []).append(e.family.value)

    facts = sorted(by_fact, key=lambda f: f.value)
    return facts, {f.value: sorted(by_fact[f]) for f in facts}


def agreement_bonus(evidence: list[Evidence]) -> tuple[int, list[str]]:
    """Corroboration across independent observations, not across modules.

    This counted FAMILIES until the overlap audit: the classifier and the
    payer rules share four of their inputs outright - the same night-window
    predicate, the same distance-from-usual-hour expression, the same
    today-against-daily-average ratio, and three separate routes to "has this
    payer paid this payee before" - and the classifier's payee features are
    the very numbers the reputation family scores. Counting modules therefore
    paid a corroboration bonus for reading one fact twice.

    It counts distinct facts now. Two families reporting HOUR_ANOMALY are one
    observation; a family reporting HOUR_ANOMALY and another reporting
    PAYEE_SHAPE are two. The bonus table is unchanged, and so is everything
    downstream of it.

    The returned names are the FACTS, which is what the bonus is actually
    counting. Use corroborating_facts() for the fact-to-family mapping.
    """
    facts, sources = corroborating_facts(evidence)

    # Two gates, and they answer different questions.
    #
    # At least two FAMILIES, because corroboration means independent streams
    # agreeing. One family making several observations is still one opinion:
    # the payer rules fire on both the amount and the hour constantly, and
    # rewarding that as if two modules had agreed turned an ordinary monthly
    # rent payment into a WARN the first time this was implemented without
    # the gate.
    #
    # Then the SIZE is the number of distinct facts, because that is what the
    # streams actually agree about, and it is where the double-counting the
    # audit found gets removed: the classifier and the reputation family both
    # reporting PAYEE_SHAPE is one thing observed twice, not two things.
    families = {name for observers in sources.values() for name in observers}

    # Corroboration is bounded by both quantities, so take the smaller.
    #
    # It cannot exceed the number of independent STREAMS: one family making
    # three observations is one opinion, and without this an ordinary monthly
    # rent payment collected a bonus for the payer rules noticing both its
    # size and its hour.
    #
    # It cannot exceed the number of distinct FACTS either: five families all
    # reading the same reputation row agree about one thing. This is the half
    # the overlap audit was about, and it is where the bonus now falls rather
    # than rises - when families collapse onto a shared fact, the fact count
    # drops below the family count and the smaller number governs.
    #
    # Taking the minimum also keeps the existing table honest. It was
    # calibrated against family counts, and facts are never fewer, so scoring
    # straight off the fact count would feed a systematically larger number
    # into an unchanged table and inflate every corroborated verdict - a
    # change to scoring dressed up as a change to bookkeeping.
    strength = min(len(facts), len(families))
    if strength < 2:
        return 0, [f.value for f in facts]
    return AGREEMENT_BONUS.get(strength, _MAX_AGREEMENT_BONUS), [f.value for f in facts]


def confidence_score(evidence: list[Evidence]) -> int:
    """0-100: how much of the evidence we would want was actually there."""
    got = sum(CONFIDENCE_WEIGHT[e.family] for e in evidence if e.available)
    return int(round(100.0 * got / _TOTAL_WEIGHT))


def evidence_level(evidence: list[Evidence]) -> EvidenceLevel:
    """Coverage as a label, for a UI that cannot render a weighted sum.

    FULL requires all three core families - the payee's history, the payer's
    behaviour and the relationship between them. Those are the families that
    let the system say anything about *this* payer paying *this* payee, and
    without them it is running on the payload alone.
    """
    present = {e.family for e in evidence if e.available}
    if all(f in present for f in _CORE):
        return EvidenceLevel.FULL
    if Family.PAYER_BEHAVIOUR in present or Family.PAYEE_HISTORY in present:
        return EvidenceLevel.PARTIAL
    return EvidenceLevel.MINIMAL


@dataclass
class Assessment:
    risk: int
    confidence: int
    level: EvidenceLevel
    verdict: str
    evidence: list[Evidence]
    agreeing: list[str] = field(default_factory=list)
    bonus: int = 0
    fact_sources: dict[str, list[str]] = field(default_factory=dict)

    @property
    def missing(self) -> list[str]:
        return sorted(e.family.value for e in self.evidence if not e.available)

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk": {
                "score": self.risk,
                "confidence": self.confidence,
                "evidence_level": self.level.value,
                "verdict": self.verdict,
            },
            "evidence": [e.as_dict() for e in self.evidence],
            "missing_evidence": self.missing,
            "agreement": {"facts": self.agreeing, "bonus": self.bonus,
                          "observed_by": self.fact_sources},
        }


def assess(evidence: list[Evidence], decide, *, findings: Optional[list] = None) -> Assessment:
    """Merge the families into one result.

    `decide` is passed in rather than imported so that the existing threshold
    and hard-block policy in payee_check stays the single definition of what a
    score means. This module combines evidence; it does not set policy.
    """
    scores = [e.score for e in evidence if e.available]
    base = combine_scores(scores)
    bonus, agreeing = agreement_bonus(evidence)
    risk = min(99, base + bonus)

    all_findings = list(findings or [])
    for e in evidence:
        all_findings.extend(e.findings)

    facts, fact_sources = corroborating_facts(evidence)

    return Assessment(
        risk=risk,
        confidence=confidence_score(evidence),
        level=evidence_level(evidence),
        verdict=decide(risk, all_findings),
        evidence=evidence,
        agreeing=agreeing,
        bonus=bonus,
        fact_sources=fact_sources,
    )
