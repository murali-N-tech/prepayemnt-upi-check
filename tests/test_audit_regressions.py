"""Regressions for the non-parser bugs found in the full-project audit.

Storage, drift detection, and the simulated dataset. Each test names the
defect it pins down.
"""

from pathlib import Path
import sys
import tempfile

sys.path.append(str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest


# ── Re-uploading a statement must not duplicate it ───────────────────────────

def _fresh_store(tmp: Path):
    import backend.app.services.profile_store as store

    store.DB_PATH = tmp / "behavior_profiles.db"
    store.DATA_DIR = tmp
    store._SCHEMA_DONE.clear()
    return store


ROW_WITHOUT_REFERENCE = {
    "timestamp": "2026-01-01T10:00:00",
    "amount": 100.0,
    "merchant": "SHOP",
    "upi_id": None,
    "status": "SUCCESS",
    # PDF statements very often carry no reference number.
    "reference_number": None,
    "raw_line": "01/01/2026 SHOP 100.00",
    "txn_type": "DEBIT",
    "time_known": True,
}


def test_re_uploading_a_statement_without_reference_numbers_is_a_no_op():
    """SQLite treats every NULL as distinct inside a UNIQUE index, so the index
    on (user_id, timestamp, amount, merchant, reference_number) suppressed
    nothing for exactly the rows that need it: a statement line with no
    reference number compared unequal to an identical stored row, and every
    re-upload inserted the whole file again. Three inserts produced three rows."""
    with tempfile.TemporaryDirectory() as d:
        store = _fresh_store(Path(d))
        first = store.save_statement_transactions("u1", "s1", "pdf", [ROW_WITHOUT_REFERENCE])
        second = store.save_statement_transactions("u1", "s2", "pdf", [ROW_WITHOUT_REFERENCE])
        third = store.save_statement_transactions("u1", "s3", "pdf", [ROW_WITHOUT_REFERENCE])
        assert (first, second, third) == (1, 0, 0)
        assert len(store.get_user_transactions("u1")) == 1


def test_two_genuinely_different_payments_are_both_kept():
    """The dedupe must not go the other way: a stricter key would have collapsed
    two real payments to the same shop for the same amount."""
    with tempfile.TemporaryDirectory() as d:
        store = _fresh_store(Path(d))
        a = dict(ROW_WITHOUT_REFERENCE)
        b = dict(ROW_WITHOUT_REFERENCE, timestamp="2026-01-01T17:45:00")
        assert store.save_statement_transactions("u1", "s1", "pdf", [a, b]) == 2


def test_time_known_survives_a_round_trip():
    with tempfile.TemporaryDirectory() as d:
        store = _fresh_store(Path(d))
        rows = [
            dict(ROW_WITHOUT_REFERENCE, timestamp="2026-01-01T10:00:00", time_known=True),
            dict(ROW_WITHOUT_REFERENCE, timestamp="2026-01-02T00:00:00", time_known=False),
        ]
        store.save_statement_transactions("u1", "s1", "pdf", rows)
        df = store.get_user_transactions("u1").sort_values("timestamp")
        assert df["time_known"].tolist() == [1, 0]


# ── Drift detection ──────────────────────────────────────────────────────────

def test_drift_is_not_declared_on_sampling_noise():
    """The old detector took the mean of the binary risk flag over ten rows a
    side and called a gap above 0.3 drift. Ten Bernoulli samples have a standard
    error near 0.16, so 0.3 is about two standard errors and the check fired on
    chance alone."""
    from backend.app.services.drift_monitor import drift_report

    rng = np.random.default_rng(7)
    stable = rng.normal(40, 12, 400)
    report = drift_report(stable[:200], stable[200:])
    assert report["status"] == "Model Stable"
    assert report["conclusive"] is True


def test_real_drift_is_still_caught():
    from backend.app.services.drift_monitor import drift_report

    rng = np.random.default_rng(7)
    before = rng.normal(40, 12, 200)
    after = rng.normal(62, 12, 200)
    report = drift_report(before, after)
    assert report["status"] == "Drift Detected"
    assert report["shift"] > 15


def test_too_little_data_is_never_reported_as_stable():
    """`{"status": "Not enough data"}` carried no drift_status key, so the UI's
    `drift_status || "Model Stable"` printed a green "Model Stable" for a check
    that had not run."""
    from backend.app.services.drift_monitor import drift_report

    report = drift_report([10, 20, 30], [40, 50, 60])
    assert report["status"] == "Not enough data"
    assert report["conclusive"] is False
    assert report["status"] != "Model Stable"


# ── The simulator must not leak the label ────────────────────────────────────

def test_payee_distinct_payers_is_a_whole_number_in_both_classes():
    """The legitimate generator wrote int(np.clip(...)) and every fraud
    generator wrote float(np.clip(rng.gamma(...))), so 99.6% of fraud rows
    carried a fractional part and no legitimate row did. One tree split on "is
    this a whole number?" separated the classes perfectly - P(fraud |
    fractional) was 1.00 against a 1.2% base rate - and every metric the
    training script reported was measuring that artefact."""
    from backend.ml.dataset import generate

    df = generate(n_transactions=20_000, seed=3)
    counts = df["payee_distinct_payers"].to_numpy()
    assert np.all(counts % 1 == 0), "a count came out fractional"

    # And the leak is gone as a predictor: the fractional test carries no
    # information because there is nothing fractional left.
    fractional = counts % 1 != 0
    assert fractional.sum() == 0


def test_no_single_feature_separates_the_classes_perfectly():
    """A guard against the next leak of this shape: if any one feature can be
    thresholded to isolate the fraud class almost perfectly, the dataset is
    broken rather than the model good."""
    from backend.ml.dataset import FEATURES, generate
    from sklearn.metrics import roc_auc_score

    df = generate(n_transactions=20_000, seed=3)
    y = df["is_fraud"].to_numpy()
    worst = max(
        (max(roc_auc_score(y, df[f]), 1 - roc_auc_score(y, df[f])), f) for f in FEATURES
    )
    auc, name = worst
    assert auc < 0.95, f"{name} alone reaches ROC-AUC {auc:.4f} - the label is leaking"
