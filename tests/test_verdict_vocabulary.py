"""One vocabulary, one mapping.

APPROVE / WARN / STEP_UP / BLOCK is the system's only risk-band vocabulary and
backend/app/core/verdict.py is its only definition. These tests hold that
shape in place, because the failure it prevents is not a crash - it is two
modules answering the same question differently and both looking right:

    the payer family had its own LOW/MEDIUM/HIGH ladder at 80 and 50, so a
    score of 75 was published as BLOCK and MEDIUM in one response

    the monitor endpoint published `risk = score > 50` and the table rendered
    it as BLOCKED / APPROVED, so 60 read as BLOCKED where the payment path
    calls 60 a STEP_UP, and 30 read as APPROVED where it calls 30 a WARN

    the offline mobile adapter classified at 65 and 35, so the same payment
    came out HIGH on a phone with no signal and MEDIUM with one

Every one of those was a second copy of a mapping that should exist once. The
tests below assert the copies are gone, not merely that they currently agree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from backend.app.core.verdict import (
    BLOCK_AT,
    STEP_UP_AT,
    VERDICTS,
    WARN_AT,
    level_from_score,
    level_from_verdict,
    verdict_from_score,
)
from backend.app.services.payee_check import _decide
from backend.app.services.personalized_risk_service import (
    band_from_score,
    evaluate_personalized_risk,
)

ROOT = Path(__file__).resolve().parents[1]


# ── The boundaries, stated as numbers ────────────────────────────────────────

@pytest.mark.parametrize("score,expected", [
    (21, "APPROVE"),
    (22, "WARN"),
    (44, "WARN"),
    (45, "STEP_UP"),
    (69, "STEP_UP"),
    (70, "BLOCK"),
])
def test_the_documented_boundaries(score, expected):
    assert verdict_from_score(score) == expected


def test_the_thresholds_are_the_published_ones():
    assert (WARN_AT, STEP_UP_AT, BLOCK_AT) == (22, 45, 70)


def test_the_bands_are_ordered_and_cover_every_score():
    seen = [verdict_from_score(s) for s in range(0, 100)]
    assert set(seen) == set(VERDICTS)
    assert [VERDICTS.index(v) for v in seen] == sorted(VERDICTS.index(v) for v in seen), (
        "a higher score can never mean a milder band"
    )


# ── One mapping, wherever a band is produced ─────────────────────────────────

def test_the_family_band_is_the_same_function():
    for score in range(0, 100):
        assert band_from_score(score) == verdict_from_score(score)


def test_the_payment_decision_is_the_same_function_when_no_finding_overrides_it():
    for score in range(0, 100):
        assert _decide(score, []) == verdict_from_score(score)


def test_identical_scores_produce_identical_verdicts_across_the_system():
    for score in (0, 21, 22, 44, 45, 69, 70, 99):
        produced = {verdict_from_score(score), band_from_score(score), _decide(score, [])}
        assert len(produced) == 1, f"score {score} classified {produced}"


def test_no_other_backend_module_defines_the_thresholds():
    owner = ROOT / "backend/app/core/verdict.py"
    pattern = re.compile(r"^(BLOCK_AT|STEP_UP_AT|WARN_AT)\s*=", re.M)
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "backend").rglob("*.py")
        if path != owner and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"a second definition of the thresholds in {offenders}"


def test_no_backend_module_compares_a_score_against_a_band_threshold():
    """The ladder is a function call, not an inline comparison anywhere else."""
    owner = ROOT / "backend/app/core/verdict.py"
    pattern = re.compile(r">=?\s*(70|45|22)\b")
    offenders = []
    for path in (ROOT / "backend").rglob("*.py"):
        if path == owner:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or not pattern.search(line):
                continue
            if "score" in line.lower() or "risk" in line.lower():
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{n}: {stripped}")
    assert offenders == [], f"an inline score-to-band comparison in {offenders}"


ALIASES = {"APPROVED", "BLOCKED", "SAFE", "FRAUD", "DECLINED", "PASS", "FAIL"}


def test_no_endpoint_renames_or_reverses_the_vocabulary():
    """A response may publish a band under an older key, but the VALUE has to be
    one of the four words - not APPROVED, not BLOCKED, not a reversed flag.

    Parsed rather than grepped, and matched exactly, so that prose recalling an
    old response shape is not mistaken for a new one.
    """
    import ast

    tree = ast.parse((ROOT / "backend/main.py").read_text(encoding="utf-8"))
    offenders = [
        f"main.py:{node.lineno} publishes {node.value!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value in ALIASES
    ]
    assert offenders == [], f"a renamed band in {offenders}"


# ── The retained legacy label cannot disagree ────────────────────────────────

def test_the_legacy_level_is_a_function_of_the_band():
    for score in range(0, 100):
        assert level_from_score(score) == level_from_verdict(verdict_from_score(score))


def test_the_legacy_level_never_contradicts_the_band():
    """HIGH exactly when BLOCK, MEDIUM exactly when STEP_UP. The old ladder sat
    at 80 and 50, which is how a BLOCK could be published as MEDIUM."""
    for score in range(0, 100):
        verdict, level = verdict_from_score(score), level_from_score(score)
        assert (level == "HIGH") == (verdict == "BLOCK")
        assert (level == "MEDIUM") == (verdict == "STEP_UP")
        assert (level == "LOW") == (verdict in {"APPROVE", "WARN"})


PROFILE = {
    "transaction_count": 200, "debit_count": 200,
    "avg_amount": 500.0, "median_amount": 400.0, "max_amount": 5000.0,
    "most_active_hour": 13, "average_daily_transactions": 2.0,
    "known_upi_ids": ["swiggy@ibl"], "favorite_merchants": ["Swiggy"],
}
HISTORY = pd.DataFrame(
    [{"timestamp": "2026-06-01T13:00:00", "merchant": "Swiggy", "amount": 480.0,
      "upi_id": "swiggy@ibl"}]
)


@pytest.mark.parametrize("amount", [90.0, 450.0, 2_000.0, 6_000.0, 20_000.0, 75_000.0])
def test_the_payer_family_publishes_a_band_and_a_label_that_agree(amount):
    r = evaluate_personalized_risk(
        profile=PROFILE, history=HISTORY, amount=amount, merchant="unknown-payee",
        timestamp="2026-06-02T23:30:00", upi_id="scam@ybl",
    )
    assert r["band"] == verdict_from_score(r["risk_score"])
    assert r["risk_level"] == level_from_verdict(r["band"])


def test_a_payer_with_no_profile_still_gets_one_vocabulary():
    r = evaluate_personalized_risk(
        profile=None, history=pd.DataFrame(), amount=20_000.0,
        merchant="anyone", timestamp="2026-06-02T12:00:00",
    )
    assert r["band"] == verdict_from_score(r["risk_score"])
    assert r["risk_level"] == level_from_verdict(r["band"])


# ── Missing evidence changes coverage, not the mapping ───────────────────────

def test_unavailable_evidence_does_not_move_the_score_to_verdict_mapping():
    """Confidence and evidence level answer "how much did we see". The band is a
    function of the score alone, and nothing about missing evidence may bend
    it - a payment nobody could check must not be banded as though it had been.
    """
    from backend.app.services.evidence import Evidence, Family, assess, unavailable

    for score in (21, 22, 44, 45, 69, 70):
        lead = Evidence(family=Family.ADDRESS, available=True, score=score,
                        severity="warn")
        # The same lead score, once with the other families measured (and
        # finding nothing) and once with them unable to look.
        full = [lead] + [
            Evidence(family=f, available=True, score=0, severity="info")
            for f in (Family.PAYEE_HISTORY, Family.PAYER_BEHAVIOUR, Family.ML_CLASSIFIER)
        ]
        thin = [lead,
                unavailable(Family.PAYEE_HISTORY, "nothing to look up"),
                unavailable(Family.PAYER_BEHAVIOUR, "no history"),
                unavailable(Family.ML_CLASSIFIER, "no baseline")]
        a, b = assess(full, _decide), assess(thin, _decide)
        assert a.risk == b.risk == score
        assert a.verdict == b.verdict == verdict_from_score(score)
        assert b.confidence < a.confidence, "coverage is where absence shows up"


# ── The offline mirror ───────────────────────────────────────────────────────

def test_the_typescript_mirror_uses_the_same_thresholds():
    """The Capacitor build classifies with no server to ask. That copy is
    allowed; disagreeing with this one is not."""
    ts = (ROOT / "src/lib/verdict.ts").read_text(encoding="utf-8")
    found = {name: int(value) for name, value in
             re.findall(r"export const (BLOCK_AT|STEP_UP_AT|WARN_AT) = (\d+);", ts)}
    assert found == {"BLOCK_AT": BLOCK_AT, "STEP_UP_AT": STEP_UP_AT, "WARN_AT": WARN_AT}
    assert re.search(r'return "BLOCK"', ts) and re.search(r'return "APPROVE"', ts)


def test_no_other_frontend_module_classifies_a_score():
    """One mirror, not one per screen. The adapter's own 65/35 ladder is the
    case this catches."""
    owner = ROOT / "src/lib/verdict.ts"
    pattern = re.compile(r'(>=|>)\s*\d+\s*\?\s*"(HIGH|MEDIUM|LOW|BLOCK|STEP_UP|WARN|APPROVE)"')
    offenders = []
    for path in list((ROOT / "src").rglob("*.ts")) + list((ROOT / "src").rglob("*.tsx")):
        if path == owner:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{n}: {stripped}")
    assert offenders == [], f"a second frontend classifier in {offenders}"


# ── The monitor endpoint ─────────────────────────────────────────────────────

def test_the_monitor_publishes_the_canonical_band_for_every_row(tmp_path, monkeypatch):
    """This endpoint used to publish `risk = score > 50` and nothing else, and
    the table rendered that as BLOCKED / APPROVED - a fourth threshold and a
    vocabulary the rest of the product does not speak.

    The payer's rows are injected rather than posted through /predict, because
    this test is about the classification the monitor publishes and nothing
    else.
    """
    from fastapi.testclient import TestClient
    from backend.app.services import profile_store
    import backend.main as main

    monkeypatch.setattr(profile_store, "DB_PATH", tmp_path / "monitor.db")

    rows = pd.DataFrame([
        {"id": 1, "amount": 240.0, "merchant": "Swiggy", "upi_id": "swiggy@ibl",
         "timestamp": "2026-09-17T13:10:00", "txn_type": "DEBIT", "status": "SUCCESS"},
        {"id": 2, "amount": 9_000.0, "merchant": "unknown-payee", "upi_id": "scam@ybl",
         "timestamp": "2026-09-17T02:30:00", "txn_type": "DEBIT", "status": "SUCCESS"},
        {"id": 3, "amount": 84_000.0, "merchant": "another-stranger", "upi_id": "mule@ybl",
         "timestamp": "2026-09-17T03:05:00", "txn_type": "DEBIT", "status": "SUCCESS"},
    ])
    monkeypatch.setattr(main, "get_user_transactions", lambda user: rows)
    monkeypatch.setattr(main, "get_behavior_profile", lambda user: PROFILE)
    main.app.dependency_overrides[main.get_current_user] = lambda: "murali@okaxis"
    try:
        client = TestClient(main.app)
        response = client.get("/transactions")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 3
    bands = set()
    for row in body:
        assert row["verdict"] == verdict_from_score(row["risk_score"])
        assert row["verdict"] in VERDICTS
        assert row["risk"] == (1 if row["verdict"] in {"STEP_UP", "BLOCK"} else 0), (
            "the legacy flag is derived from the band, so it cannot disagree"
        )
        bands.add(row["verdict"])
    assert len(bands) > 1, "these three payments should not all land in one band"
