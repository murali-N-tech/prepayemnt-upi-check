"""The pre-payment check.

Combines views of a payment that has not happened yet:

  1. the address itself   - is it valid, does it impersonate someone (vpa.py)
  2. the QR payload       - was the request tampered with (upi_qr.py)
  3. the payee's history  - what has everyone else's money done here
                            (payee_reputation.py)
  4. the stated purpose   - does it contradict the payee (intent.py)
  5. the pressure         - what does the message that caused this say
                            (coercion.py)

and, when the payer is known, their own behaviour baseline. The output is a
four-way decision rather than approve/block, because the useful answer for a
pre-payment product is usually the middle: "this payee is nine days old and
24 people have paid it once each - are you sure?"

Streams 4 and 5 exist because of a measured gap. The payer-behaviour and
payee-graph streams together catch 58.4% of social-engineering fraud at a 1%
false-positive budget. The rest is missed structurally: in that fraud class
the payer behaves normally, because they were persuaded. The evidence is not
in the transaction - it is in the instruction that produced it, and in the
mismatch between what the payer thinks they are doing and who actually
receives the money.

The combination rule matters as much as the streams. A single stream must not
reach BLOCK on weak evidence, but independent streams AGREEING is much stronger
than any of them alone - so agreement across families earns a bonus, while two
findings from the same family do not.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from backend.app.core.upi_limits import cap_for, check_amount, standard_cap
from backend.app.services.coercion import analyse_message
from backend.app.services.intent import analyse_intent
from backend.app.services.payee_reputation import (
    assess_payee,
    connect,
    payee_key,
    payer_has_paid,
)
from backend.app.services.scam_link import analyse_links, brand_conflicts_with_payee
from backend.app.services.graph_cache import graph_view
from backend.app.services.evidence import (
    Evidence,
    Fact,
    Family,
    NON_VOTING,
    agreement_bonus,
    assess,
    combine_scores,
    confidence_score,
    evidence_level,
    unavailable,
)
from backend.app.core.verdict import (
    BLOCK_AT,
    STEP_UP_AT,
    VERDICTS,
    WARN_AT,
    verdict_from_score,
)
from backend.app.services.personalized_risk_service import evaluate_personalized_risk
from backend.app.services.upi_qr import parse_upi_target
from backend.app.services.vpa import VpaFinding, graded, total_weight
from backend.ml.features import (
    MIN_PAYMENTS_FOR_AMOUNT_BASELINE,
    PAYEE_HISTORY_FEATURES,
    amount_baseline_is_measurable,
    build_vector,
)
from backend.models.ensemble_model import load_metrics, load_model

# Decision thresholds and the score -> verdict mapping, re-exported from
# backend/app/core/verdict.py so that the names existing callers and tests
# import from here keep working. The definition is there and only there: this
# module used to hold one copy of the ladder while personalized_risk_service
# held another.

SEVERITY_ORDER = {"info": 0, "warn": 1, "high": 2, "critical": 3}

# Above this, a payment to a payee nobody has a history with is worth stopping
# for even when nothing else looks wrong.
LARGE_AMOUNT = 25_000

# Findings that decide the outcome on their own, whatever the arithmetic says.
HARD_BLOCK = {
    "payee_blocked", "vpa_malformed", "not_a_payment_link", "no_payee", "empty",
    # A request for more than the network can carry cannot be a genuine payment
    # request, whatever the rest of the arithmetic says.
    "amount_over_upi_limit",
}


# ── The behavioural families ────────────────────────────────────────────────
# Both of these read the payer. They are kept apart because they answer
# different questions - the rules ask "is this unusual for this person?", the
# classifier asks "does this resemble fraud the model was fitted on?" - but
# they read overlapping facts, and that overlap is handled at the agreement
# bonus rather than by pretending it is not there.

# The model contributes to the score and casts NO agreement vote.
#
# The bonus exists to reward independent streams corroborating each other. The
# classifier is not one: it reads the payer's amount, hour and velocity (which
# is what the payer-behaviour rules read) and the payee's age, payer count and
# repeat ratio (which is what the reputation family reads). A vote from it
# would be the same evidence counted a second time under a different name, and
# a payment flagged by the reputation family alone would collect a two-family
# bonus for what is one observation.
ML_CASTS_AGREEMENT_VOTE = False

# The wire names of the families that score but do not vote. The set itself is
# evidence.NON_VOTING; this is the same thing spelled the way the response is,
# so there is one list and not two that can drift apart.
NON_VOTING_FAMILIES = frozenset(f.value for f in NON_VOTING)

# The classifier alone tops out below BLOCK_AT, so it can reach STEP_UP on its
# own but needs corroboration to block outright. Not a statement that the model
# is untrustworthy - it is calibrated, and Brier skill is reported - but it is
# the family most exposed to input the training distribution never covered, and
# a block is the one verdict a user cannot easily work around. Corroborated, it
# blocks: the agreement bonus lifts a jointly-flagged payment past 70.
ML_SOLO_CEILING = 66

# Below this the payer-behaviour rules are describing an ordinary payment.
# Their score floors at 5 for a perfectly normal one, and feeding that through
# would put a permanent floor under every assessment.
PAYER_NOTABLE_AT = 25



# A fact is the model's only when removing it materially moves the reading.
# Relative, with an absolute floor: on a payment sitting at 0.08 a drop of
# 0.03 is most of the signal, while on one sitting at 0.75 it is noise.
ML_FACT_RELATIVE = 0.15
ML_FACT_FLOOR = 0.01

# Each probe answers "what would the model say if this payment were ordinary
# in exactly this one respect?" - so the fact is attributed only when it is
# doing real work.
#
# The payee probe blanks the payee features to NaN, which is an input the
# model was fitted on (a quarter of the training rows carry it) rather than a
# substitution. The others replace a feature with the payer's own benign
# value, which IS a substitution - acceptable here because the result is used
# only to attribute a fact, never to produce a score. No probe touches the
# number this family reports.
ML_PROBES: dict[Fact, dict[str, float]] = {
    Fact.VELOCITY_HOURLY: {"seconds_since_last_txn": 9000.0, "txns_last_hour": 0.0},
    Fact.VELOCITY_DAILY: {"txns_today_over_avg": 1.0},
    Fact.AMOUNT_DEVIATION: {"amount_over_user_avg": 1.0},
    Fact.HOUR_ANOMALY: {"is_night": 0.0, "hours_from_usual": 0.0},
    Fact.PAYEE_FAMILIARITY: {"payee_is_new": 0.0},
}


def _ml_facts(model, vector, probability: float) -> frozenset:
    """Which underlying observations this probability actually rests on.

    Declaring every fact the model READS would be wrong, and wrong in the
    direction that matters: the classifier reads six of them, so a single
    family scoring on its own would supply six corroborating facts and take
    the top of the bonus table by itself. Corroboration means separate
    observations agreeing, and one model emitting one number is one
    observation however many columns went into it.

    So each fact is tested by counterfactual. Six extra single-row
    predictions, microseconds apiece, well inside the pre-payment budget.
    """
    import numpy as np

    base = vector.frame()
    found = []
    threshold = max(ML_FACT_FLOOR, ML_FACT_RELATIVE * probability)

    if vector.payee_history_available:
        blind = base.copy()
        for column in PAYEE_HISTORY_FEATURES:
            blind[column] = np.nan
        blind["payee_history_available"] = 0.0
        if probability - float(model.predict_proba(blind)[0, 1]) >= threshold:
            found.append(Fact.PAYEE_SHAPE)

    for fact, neutral in ML_PROBES.items():
        probe = base.copy()
        for column, value in neutral.items():
            probe[column] = value
        if probability - float(model.predict_proba(probe)[0, 1]) >= threshold:
            found.append(fact)

    return frozenset(found)


def _ml_evidence(
    amount: Optional[float],
    timestamp: Optional[str],
    profile: Optional[dict[str, Any]],
    reputation_dict: Optional[dict[str, Any]],
    seen_before: Optional[bool],
    velocity: dict[str, float],
) -> dict[str, Any]:
    """The calibrated classifier as one evidence family.

    Returns available=False and score=None whenever the features the model
    needs cannot be measured. It does NOT fall back to a population-typical
    payer, because a made-up payer profile produces a made-up probability and
    the whole point of the evidence-availability work is that the system says
    "we could not check" instead of guessing quietly.

    Missing PAYEE history is a different case and does not disable the family.
    The model is fitted on a corpus where a quarter of rows carry no payee
    history at all (backend/ml/dataset.apply_observation_mask), so NaN there is
    an input it has learned a response to rather than a gap to paper over.
    """
    unavailable = {"available": False, "score": None, "severity": None,
                   "code": "ml_unavailable", "model": None,
                   "facts": [], "_facts": frozenset()}

    if not amount or amount <= 0:
        return {**unavailable,
                "message": "The payment amount is not known yet, so the behavioural "
                           "model has nothing to score."}
    if not profile:
        return {**unavailable,
                "message": "No payment history for this payer, so the behavioural "
                           "model cannot compare this payment against anything. "
                           "Import a statement to enable it."}
    if not amount_baseline_is_measurable(profile):
        # The model reads amount_over_user_avg as a real number - it was not
        # trained with that column missing, so a NaN here would be an input it
        # has never seen. Reporting the family unavailable is the honest move:
        # with fewer than a handful of prior payments the denominator is a
        # single observation, and a ratio against it is arithmetic rather than
        # evidence.
        return {**unavailable,
                "message": (
                    f"This payer has fewer than {MIN_PAYMENTS_FOR_AMOUNT_BASELINE} "
                    "recorded payments, so there is no spending baseline to compare "
                    "this one against."
                )}

    try:
        model = load_model()
        threshold = float(
            load_metrics().get("selected", {}).get("operating_point", {}).get("threshold", 0.5)
        )
    except RuntimeError as exc:
        # An untrained or version-mismatched artefact. The rest of the checks
        # must keep working; this family reports itself absent and says why.
        return {**unavailable, "code": "ml_model_unavailable",
                "message": f"The behavioural model is not loadable here: {exc}".split(chr(10))[0]}

    vector = build_vector(
        amount=float(amount),
        timestamp=timestamp,
        profile=profile,
        reputation=reputation_dict or {},
        payer_seen_payee_before=seen_before,
        **velocity,
    )
    probability = float(model.predict_proba(vector.frame())[0, 1])

    if probability < threshold:
        score = int(round(graded(0.0, threshold, probability, 0, 18)))
        severity = "warn" if score >= 6 else "info"
        message = (f"The behavioural model puts this below its alert threshold "
                   f"({probability:.0%} against {threshold:.0%}).")
    else:
        score = int(round(graded(threshold, 0.80, probability, 30, ML_SOLO_CEILING)))
        severity = "high"
        message = (f"The behavioural model scores this payment {probability:.0%}, "
                   f"above its {threshold:.0%} alert threshold. It compares the "
                   f"amount, timing and velocity against this payer's own history.")

    missing = vector.missing()
    if missing and probability >= threshold:
        message += (" Payee history was not available, so this reading rests on "
                    "the payer's own behaviour.") if not vector.payee_history_available else ""

    facts = _ml_facts(model, vector, probability)

    return {
        "available": True,
        "score": score,
        "severity": severity,
        "code": "ml_behavioural_risk",
        "message": message,
        "facts": sorted(f.value for f in facts),
        "_facts": facts,
        "probability": round(probability, 4),
        "threshold": threshold,
        "payee_history_available": vector.payee_history_available,
        "features_unavailable": missing,
        "model": {
            "kind": type(model).__name__,
            "features": len(vector.values),
            "operating_point": threshold,
        },
    }


def _payer_evidence(
    profile: Optional[dict[str, Any]],
    history: Optional[Any],
    amount: Optional[float],
    merchant: str,
    timestamp: str,
    upi_id: Optional[str],
) -> dict[str, Any]:
    """The payer's own baseline, as a family rather than as a second verdict.

    evaluate_personalized_risk still returns a LOW/MEDIUM/HIGH `risk_level`
    for the older endpoints that render it. Nothing here reads it. A second
    verdict vocabulary alongside APPROVE/WARN/STEP_UP/BLOCK is what produced
    the reconciliation that used to sit in main.py, where a payee-side APPROVE
    was nudged to WARN whenever the payer-side string happened to say HIGH -
    two scales meeting in an if-statement with no stated rule. The score is
    evidence; the band is decided once, at the end, for the whole assessment.
    """
    unavailable = {"available": False, "score": None, "severity": None,
                   "code": "payer_history_unavailable", "detail": None,
                   "facts": [], "_facts": frozenset()}

    if not profile or not amount or amount <= 0:
        return {**unavailable,
                "message": "No payment history for this payer, so this payment "
                           "cannot be compared against their usual behaviour."}

    import pandas as _pd

    assessment = evaluate_personalized_risk(
        profile=profile,
        history=history if history is not None else _pd.DataFrame(),
        amount=float(amount),
        merchant=merchant,
        timestamp=timestamp,
        upi_id=upi_id,
    )
    if not assessment.get("profile_available"):
        return {**unavailable,
                "message": "No payment history for this payer, so this payment "
                           "cannot be compared against their usual behaviour."}

    fired = frozenset(Fact(f) for f in assessment.get("facts", []))
    raw = int(assessment.get("risk_score") or 0)
    if raw < PAYER_NOTABLE_AT:
        score, severity = 0, "info"
        message = "This payment fits the payer's usual amount, timing and payees."
    else:
        score = int(round(graded(PAYER_NOTABLE_AT, 85, raw, 12, 52)))
        severity = "high" if score >= 24 else "warn"
        reasons = [r for r in assessment.get("reasons", []) if r]
        message = "Unusual for this payer: " + "; ".join(reasons[:3]) + "."

    return {
        "available": True,
        "score": score,
        "severity": severity,
        "code": "payer_behaviour",
        "message": message,
        "facts": sorted(f.value for f in fired),
        "_facts": fired,
        "detail": assessment,
    }


# The combination rule lives in backend/app/services/evidence.py, which is the
# single definition of how family scores become one number. It used to be
# duplicated here; two copies of an arithmetic rule is how the agreement table
# ends up fixed in one place and not the other.
#
# What stays here is POLICY: the thresholds, the hard-block set and _decide.
# evidence.py combines; this module decides what a combined score means.



def _lead(findings: list[VpaFinding]) -> tuple[str, str, str]:
    """The finding a family is reported by: its most severe one.

    A family speaks with one voice in the response even when it raised six
    findings - the full list is still carried in `findings` - because the
    evidence row is what the agreement rule and the UI read, and six rows from
    one family would read as six streams agreeing.
    """
    if not findings:
        return "info", "", ""
    worst = max(findings, key=lambda f: SEVERITY_ORDER[f.severity])
    return worst.severity, worst.code, worst.message


def _family(kind: Family, score: int, findings: list[VpaFinding],
            facts: "frozenset[Fact] | set[Fact]" = frozenset()) -> Evidence:
    severity, code, message = _lead(findings)
    return Evidence(family=kind, available=True, score=int(score),
                    severity=severity, code=code, message=message,
                    findings=list(findings), facts=frozenset(facts))


# Which underlying observation each payee-reputation finding rests on. Reports
# from other users are a genuinely separate fact from the shape of the inflow -
# one is what people said, the other is what the money did - so they can
# corroborate each other.
_REPUTATION_FACTS = {
    "payee_reported": Fact.PAYEE_REPORTS,
    "payee_blocked": Fact.PAYEE_REPORTS,
}


def _reputation_facts(findings: list[VpaFinding]) -> frozenset:
    facts = {_REPUTATION_FACTS.get(f.code, Fact.PAYEE_SHAPE) for f in findings}
    return frozenset(facts)


def _decide(score: int, findings: list[VpaFinding]) -> str:
    """Policy: the findings that override the arithmetic, then the arithmetic.

    The band itself is verdict_from_score and is not re-implemented here.
    """
    if any(f.code in HARD_BLOCK for f in findings):
        return "BLOCK"
    return verdict_from_score(score)


HEADLINES = {
    "APPROVE": "Nothing suspicious found",
    "WARN": "Worth a second look before you pay",
    "STEP_UP": "Verify the payee before sending money",
    "BLOCK": "Do not pay this",
}


def check_payee(
    payload: str,
    payer_id: Optional[str] = None,
    amount: Optional[float] = None,
    conn: Optional[sqlite3.Connection] = None,
    intent: Optional[str] = None,
    message: Optional[str] = None,
    profile: Optional[dict[str, Any]] = None,
    history: Optional[Any] = None,
    timestamp: Optional[str] = None,
    velocity: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """`payload` is a scanned QR, a pasted UPI ID, or a phone number.

    `intent` is what the payer says they are doing; `message` is the text that
    prompted the payment. Both optional - every existing caller keeps working,
    and their absence is never treated as evidence that a payment is safe.

    `profile`, `history` and `velocity` are the payer's own record, passed in
    rather than looked up here so that identity stays the caller's decision:
    main.py resolves the payer from the bearer token and hands over what that
    token is entitled to. A payer_id in a request body can therefore never
    widen what gets read.

    This function is the whole risk assembly. Every family is scored here and
    merged here, including the behavioural classifier, which used to be run
    separately in main.py and reconciled with an if-statement afterwards.
    """
    qr = parse_upi_target(payload)

    key = payee_key(qr.payee_vpa, qr.payee_name)

    # One connection for the whole assessment. Three lookups need the store -
    # the reputation row, this payer's own edge, and the graph cache - and
    # opening a connection for each meant three schema checks per check on a
    # database file that may sit on a network mount. Opening one and closing it
    # here is both faster and the difference between working and not.
    _own_conn = conn is None
    if _own_conn and key:
        conn = connect()
    try:
        return _assemble(payload, qr, key, conn, payer_id, amount, intent, message,
                         profile, history, timestamp, velocity)
    finally:
        if _own_conn and conn is not None:
            conn.close()


def _assemble(payload, qr, key, conn, payer_id, amount, intent, message,
              profile, history, timestamp, velocity) -> dict[str, Any]:
    reputation = assess_payee(key, conn=conn) if key else None

    findings: list[VpaFinding] = list(qr.all_findings)
    if reputation:
        findings.extend(reputation.findings)

    # Size matters when the payee is a stranger. A small payment to an unknown
    # address is how most people meet a new merchant; a large one is how most
    # people lose money.
    amount_findings: list[VpaFinding] = []
    effective_amount = qr.amount if qr.amount is not None else (amount or None)

    # An amount the caller typed, checked against the cap that applies to THIS
    # payee. upi_qr already does this for an amount baked into the QR; a typed
    # one reached here unchecked, so "Rs 99,99,999 to a payee with no
    # established history" came back WARN - a considered-looking verdict on a
    # payment UPI would refuse outright.
    # Only the OVER-cap case. A zero or missing amount means the payer has not
    # told us the amount yet - the pre-payment screen sends 0 before they type
    # one - so treating it as a violation blocked the payment under a finding
    # code that was simply untrue ("amount_over_upi_limit" for Rs 0).
    if qr.amount is None and amount is not None and amount > 0:
        if amount > cap_for(qr.merchant_code, qr.signed):
            problem = check_amount(amount, qr.merchant_code, qr.signed)
            amount_findings.append(
                VpaFinding("amount_over_upi_limit", "critical",
                           problem or "That amount is more than UPI can carry.")
            )
    established = bool(
        reputation and any(f.code == "payee_established" for f in reputation.findings)
    )
    if effective_amount and effective_amount >= LARGE_AMOUNT and not established:
        # Weighted by how large, not just "large". This was a plain boolean, so
        # Rs 25,000 and Rs 99,000 both contributed exactly 35 - the same
        # evidence for a fifth of the daily limit as for all of it. The scale
        # runs from the bottom of the high band at the LARGE_AMOUNT threshold
        # to the top of it at the UPI per-transaction cap, so the number moves
        # with the money actually at risk.
        amount_findings.append(
            VpaFinding("large_to_unfamiliar", "high",
                       f"Rs {effective_amount:,.0f} to a payee with no established "
                       f"history here. Confirm who you are paying first.",
                       weight=graded(LARGE_AMOUNT, standard_cap(), effective_amount, 24, 52))
        )
    findings.extend(amount_findings)

    amount_score = total_weight(amount_findings)

    # ── The stated purpose, checked against who actually gets the money ──────
    is_phone_payee = qr.kind == "phone" or bool(
        qr.vpa_analysis and getattr(qr.vpa_analysis, "from_phone", False)
    )
    intent_result = analyse_intent(
        intent,
        merchant_code=qr.merchant_code,
        is_phone_payee=is_phone_payee,
        established=established,
        payee_name=qr.payee_name,
    )
    findings.extend(intent_result.findings)

    # ── The pressure behind the payment ─────────────────────────────────────
    coercion = analyse_message(message)
    coercion_findings = [
        VpaFinding(
            f"message_{f.code}",
            f.severity,
            f.message + (f': "{f.quote}"' if f.quote else ""),
        )
        for f in coercion.findings
    ]
    # The message score is the fitted probability, not a sum of severities: the
    # whole point of fitting it was that the patterns are worth different
    # amounts, and several weak ones must not add up to a strong one.
    # A gated message (only the cues genuine institutions also use) must not
    # count as an agreeing stream - the response would otherwise carry both
    # "this alone is not treated as pressure" and a verdict escalated by it.
    coercion_score = 0 if (not coercion.supplied or coercion.weak_only) else coercion.score
    findings.extend(coercion_findings)
    if coercion.language_note:
        findings.append(VpaFinding("message_language", "info", coercion.language_note))

    # ── Any link carried by the message or the QR ───────────────────────────
    # Both sources: upi_qr.py already noticed when a QR payload carries a url
    # parameter, but it could only say that one existed.
    # The QR payload's own url= parameter is pulled out by upi_qr and analysed
    # here; upi_qr no longer scores it, so the same link cannot be counted in
    # two "independent" families and earn the agreement bonus on its own.
    link_source = " ".join(filter(None, [message, payload, qr.embedded_url]))
    links = analyse_links(link_source)
    link_findings = list(links.findings)
    conflict = brand_conflicts_with_payee(links, qr.payee_vpa)
    if conflict:
        link_findings.append(conflict)
    findings.extend(link_findings)
    link_score = min(100, links.score + (conflict.scored() if conflict else 0))

    # ── The payer's own behaviour, and the classifier ───────────────────────
    import pandas as _pd

    when = timestamp or _pd.Timestamp.now().isoformat()
    payer = _payer_evidence(
        profile=profile,
        history=history,
        amount=effective_amount,
        merchant=qr.payee_name or qr.payee_vpa or "",
        timestamp=when,
        upi_id=qr.payee_vpa,
    )
    seen_before = None
    if payer_id and key:
        seen_before = payer_has_paid(key, payer_id, conn=conn)

    ml = _ml_evidence(
        amount=effective_amount,
        timestamp=when,
        profile=profile,
        reputation_dict=reputation.as_dict() if reputation else None,
        seen_before=seen_before,
        velocity=velocity or {},
    )

    for family in (payer, ml):
        if family["available"] and family["score"]:
            findings.append(VpaFinding(family["code"], family["severity"], family["message"]))

    # An unavailable family is absent from the arithmetic, not present as a
    # zero. A zero is a measurement - "we looked and there is nothing wrong" -
    # and letting "we could not look" wear the same number is how an unchecked
    # payment comes to read as a checked one. Evidence.__post_init__ refuses to
    # construct an unavailable row that carries a score, so the two cannot be
    # confused by accident anywhere downstream.
    # Each family declares the observations its score rests on. The agreement
    # bonus counts DISTINCT facts, so two families reading the same timestamp
    # or the same reputation row corroborate once between them rather than
    # twice. See evidence.Fact for why.
    evidence: list[Evidence] = [
        _family(Family.ADDRESS, qr.score, list(qr.all_findings), {Fact.ADDRESS_INTEGRITY}),
        _family(Family.SCAM_LINKS, link_score, link_findings, {Fact.LINK_REPUTATION}),
    ]

    if reputation is not None:
        evidence.append(_family(Family.PAYEE_HISTORY, reputation.score,
                                list(reputation.findings),
                                _reputation_facts(list(reputation.findings))))
    else:
        evidence.append(unavailable(
            Family.PAYEE_HISTORY,
            "No address could be read from this input, so there is nothing to "
            "look up."))

    if effective_amount is not None:
        # Size against what the rail permits and against what a stranger
        # plausibly receives - not against this payer's own norm, which is
        # AMOUNT_DEVIATION and belongs to the behavioural families.
        evidence.append(_family(Family.AMOUNT_CONTEXT, amount_score, amount_findings,
                                {Fact.AMOUNT_ABSOLUTE}))
    else:
        evidence.append(unavailable(
            Family.AMOUNT_CONTEXT,
            "The payment amount is not known yet."))

    if intent:
        evidence.append(_family(Family.STATED_PURPOSE, intent_result.score,
                                list(intent_result.findings), {Fact.STATED_PURPOSE}))
    else:
        evidence.append(unavailable(
            Family.STATED_PURPOSE,
            "The payer has not said what this payment is for."))

    if coercion.supplied:
        evidence.append(_family(Family.MESSAGE_PRESSURE, coercion_score, coercion_findings,
                                {Fact.MESSAGE_COERCION}))
    else:
        evidence.append(unavailable(
            Family.MESSAGE_PRESSURE,
            "No message was supplied, so there is no wording to examine."))

    # The payer's own history with THIS payee. A first payment is not evidence
    # of fraud and carries no score - people pay new payees constantly, and the
    # amount family already handles "large, and to a stranger". What this row
    # contributes is certainty: knowing the relationship is established, or
    # knowing for a fact that it is not, is worth more to the reader than any
    # number it could produce.
    if seen_before is None:
        evidence.append(unavailable(
            Family.RELATIONSHIP,
            "No authenticated payer, so this payer's own history with this "
            "payee cannot be read."))
    else:
        evidence.append(Evidence(
            family=Family.RELATIONSHIP, available=True, score=0, severity="info",
            facts={Fact.PAYEE_FAMILIARITY},
            code="relationship_established" if seen_before else "relationship_new",
            message=("You have paid this payee before." if seen_before
                     else "This is your first payment to this payee. That is "
                          "ordinary on its own."),
        ))

    for family_kind, produced in ((Family.PAYER_BEHAVIOUR, payer), (Family.ML_CLASSIFIER, ml)):
        if produced["available"]:
            evidence.append(Evidence(
                family=family_kind, available=True, score=int(produced["score"]),
                severity=produced["severity"], code=produced["code"],
                message=produced["message"], facts=produced.get("_facts", frozenset()),
            ))
        else:
            evidence.append(unavailable(family_kind, produced["message"]))

    # Read from the structures the observation path maintains. No rebuild:
    # one indexed lookup for shape, one bounded two-hop query for overlap.
    #
    # The fact split here is the part worth reading twice. Shape findings -
    # how many payers, how few returned, how tightly they arrived - are the
    # same observation the reputation family already reports, so they are
    # tagged PAYEE_SHAPE and collapse into it. Only the overlap finding, which
    # is about where this address sits relative to OTHER addresses, is
    # something no other family can see, and only that earns GRAPH_POSITION.
    # Emitting GRAPH_POSITION merely because a graph exists would manufacture
    # corroboration out of the system having a graph at all.
    # Reuse the caller's connection where there is one; otherwise open and
    # close our own rather than leaking it for the process lifetime.
    graph = graph_view(conn, key) if (key and conn is not None) else None
    if graph is None or not graph.available:
        evidence.append(unavailable(
            Family.GRAPH,
            graph.unavailable_because if graph else
            "No address could be read from this input."))
    else:
        # This family scores ONLY what no other family can see.
        #
        # The graph view also computes the payee's shape - how many payers,
        # how few returned, how tightly they arrived - because the overlap
        # logic needs it and the dashboard reports it. But the reputation
        # family already scores that same observation, and scoring it twice
        # inflates the total even when fact-awareness correctly withholds the
        # agreement bonus: the damped-max rule adds 0.4 of the second reading
        # whatever tag it carries. A legitimate new shop with twelve customers
        # and no repeats went from STEP_UP to BLOCK on exactly that, scored
        # once at 64 by reputation and again at 70 here for the same twelve
        # customers.
        #
        # So shape is reported for the reader and weighted at zero, and the
        # only thing this family scores is payer overlap - where this address
        # sits relative to OTHER addresses, which nothing else observes.
        shape_findings = [
            VpaFinding("graph_payee_shape", "info", text, weight=0)
            for text in graph.shape_findings
        ]
        position_findings = [
            VpaFinding("graph_payer_overlap", "critical", text)
            for text in graph.position_findings
        ]
        findings.extend(shape_findings + position_findings)

        # GRAPH_POSITION only when an actual positional finding fired. Not
        # because a graph exists, and not because the payee has a position in
        # it - every address in a connected payment network has one.
        graph_facts = {Fact.GRAPH_POSITION} if position_findings else set()
        evidence.append(_family(Family.GRAPH, total_weight(position_findings),
                                shape_findings + position_findings, graph_facts))

    assessment = assess(evidence, _decide, findings=findings)
    score = assessment.risk
    bonus, agreeing = assessment.bonus, assessment.agreeing
    family_scores = {e.family.value: e.score for e in evidence if e.available}

    if bonus:
        findings.append(VpaFinding(
            "streams_agree", "high",
            f"{len(agreeing)} independent things about this payment look wrong "
            f"({', '.join(a.replace('_', ' ') for a in agreeing)}). Any one of them "
            f"alone would be worth a second look; together they are the reason for "
            f"this verdict."
        ))

    # Re-decided after the agreement finding is appended so a hard block added
    # by any family still dominates. assess() already called _decide once; this
    # is the same policy applied to the final finding list.
    decision = _decide(score, findings)

    findings.sort(key=lambda f: -SEVERITY_ORDER[f.severity])

    return {
        "input": payload,
        "input_kind": qr.kind,
        "payee": {
            "vpa": qr.payee_vpa,
            "key": key,
            "display_name": qr.payee_name or (reputation.display_name if reputation else None),
            "valid": bool(qr.vpa_analysis and qr.vpa_analysis.valid),
            "handle_type": qr.vpa_analysis.handle_type if qr.vpa_analysis else "unknown",
            "impersonates": qr.vpa_analysis.impersonates if qr.vpa_analysis else None,
        },
        "request": {
            "amount": qr.amount if qr.amount is not None else amount,
            "amount_locked": qr.amount_locked,
            "note": qr.note,
            "merchant_code": qr.merchant_code,
            "signed": qr.signed,
        },
        "reputation": reputation.as_dict() if reputation else None,
        "decision": decision,
        "headline": HEADLINES[decision],
        "intent": intent_result.as_dict(),
        "message_pressure": coercion.as_dict(),
        "links": links.as_dict(),
        # ── Canonical contract ──────────────────────────────────────────
        "risk_score": score,
        "confidence_score": assessment.confidence,
        "evidence_level": assessment.level.value,
        "verdict": decision,
        "evidence": [e.as_dict() for e in evidence],
        "missing_evidence": assessment.missing,
        # ── Kept for the existing UI, which reads these ─────────────────
        "component_scores": family_scores,
        "evidence_available": {e.family.value: e.available for e in evidence},
        "ml": ml,
        "payer_behaviour": payer,
        "graph": graph.as_dict() if graph else None,
        # `facts` is what the bonus counts. `observed_by` names the families
        # that reported each one, so a reader can see two modules collapsing
        # into one observation rather than wondering why four flagging
        # families earned no corroboration.
        "agreement": {"facts": agreeing, "bonus": bonus,
                      "observed_by": assessment.fact_sources},
        "findings": [
            {"code": f.code, "severity": f.severity, "message": f.message} for f in findings
        ],
        "checked_by": payer_id,
    }
