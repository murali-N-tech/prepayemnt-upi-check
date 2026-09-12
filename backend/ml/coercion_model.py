"""Fit the coercion detector and report what it is actually worth.

Ten binary features and a logistic regression. That is deliberate, not a
shortcut - see the note at the top of backend/app/services/coercion.py. The
contribution of this feature is the FUSION of three evidence streams, and the
text model is one input to it; an opaque text model would defeat the purpose,
because the explanation is what the payer acts on.

Output is models/coercion_weights.json: ten coefficients, an intercept, and
the metrics below. JSON rather than a pickle - a scikit-learn pickle is bound
to the numpy version that wrote it, this project has already lost time to
exactly that, and ten numbers do not need a binary format.

    python -m backend.ml.coercion_model
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from backend.app.services.coercion import (  # noqa: E402
    FEATURE_ORDER,
    STRONG_PATTERNS,
    WEAK_PATTERNS,
    apply_policy,
    extract_features,
)


def gated_scores(probs, X) -> "np.ndarray":
    """The score the service actually acts on, weak-cue ceiling included.

    Reporting the raw model would describe a function that does not ship."""
    out = []
    for prob, row in zip(probs, X):
        features = {code: int(v) for code, v in zip(FEATURE_ORDER, row)}
        score, _ = apply_policy(float(prob), features)
        out.append(score / 100.0)
    return np.array(out)

CORPUS = ROOT / "data" / "coercion_corpus.jsonl"
OUT = ROOT / "models" / "coercion_weights.json"
SEED = 42

# The threshold is CHOSEN, not defaulted to 0.5, and it is chosen against the
# hard negatives: how much shouting at genuine bank messages is acceptable.
# The main classifier uses a 1% budget; this one is looser at 5% because a
# message warning is advisory and sits alongside four other streams, whereas
# the classifier's flag stands alone. Stating the difference rather than
# implying they are the same number.
HARD_FP_BUDGET = 0.05


def choose_threshold(probs, kinds, budget: float = HARD_FP_BUDGET) -> float:
    """Lowest threshold whose hard-negative false-positive rate fits the budget."""
    import numpy as _np
    hard = _np.array([k == "hard_negative" for k in kinds])
    if not hard.any():
        return 0.5
    for t in _np.round(_np.arange(0.05, 0.99, 0.01), 2):
        if float((probs[hard] >= t).mean()) <= budget:
            return float(t)
    return 0.99


def load_corpus() -> tuple[list[str], np.ndarray, list[str]]:
    if not CORPUS.exists():
        raise SystemExit(
            f"No corpus at {CORPUS}.\n\n"
            "    Build it:  python scripts/build_coercion_corpus.py"
        )
    texts, labels, kinds = [], [], []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        texts.append(row["text"])
        labels.append(int(row["label"]))
        kinds.append(row["kind"])
    return texts, np.array(labels), kinds


def to_matrix(texts: list[str]) -> np.ndarray:
    return np.array([[extract_features(t)[c] for c in FEATURE_ORDER] for t in texts])


def per_pattern_report(X: np.ndarray, y: np.ndarray) -> dict[str, dict]:
    """How trustworthy is each pattern ON ITS OWN?

    This is the table that says which cues are evidence and which are noise.
    A pattern that fires as often on real bank messages as on scams is not a
    fraud signal, however intuitive it feels.
    """
    report = {}
    for i, code in enumerate(FEATURE_ORDER):
        fired = X[:, i] == 1
        n = int(fired.sum())
        if n == 0:
            report[code] = {"fires_on": 0, "precision": None, "recall": None}
            continue
        tp = int((fired & (y == 1)).sum())
        report[code] = {
            "fires_on": n,
            "precision": round(tp / n, 3),
            "recall": round(tp / max(int((y == 1).sum()), 1), 3),
        }
    return report


def main() -> None:
    texts, y, kinds = load_corpus()
    X = to_matrix(texts)

    idx_train, idx_test = train_test_split(
        np.arange(len(y)), test_size=0.30, random_state=SEED, stratify=y
    )
    X_train, X_test = X[idx_train], X[idx_test]
    y_train, y_test = y[idx_train], y[idx_test]
    kinds_test = [kinds[i] for i in idx_test]

    model = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED)
    model.fit(X_train, y_train)

    # Threshold is picked on TRAIN probabilities, never on the test set.
    train_probs = gated_scores(model.predict_proba(X_train)[:, 1], X_train)
    kinds_train = [kinds[i] for i in idx_train]
    threshold = choose_threshold(train_probs, kinds_train)

    probs = gated_scores(model.predict_proba(X_test)[:, 1], X_test)
    preds = (probs >= threshold).astype(int)

    # The headline safety number: how often does this shout at a real bank SMS?
    hard = np.array([k == "hard_negative" for k in kinds_test])
    easy = np.array([k == "easy_negative" for k in kinds_test])
    hard_fp = float(preds[hard].mean()) if hard.any() else 0.0
    easy_fp = float(preds[easy].mean()) if easy.any() else 0.0

    scam = y_test == 1
    recall = float(preds[scam].mean()) if scam.any() else 0.0

    coefficients = {code: round(float(c), 4) for code, c in zip(FEATURE_ORDER, model.coef_[0])}

    metrics = {
        "corpus": {
            "total": int(len(y)),
            "scam": int((y == 1).sum()),
            "hard_negative": kinds.count("hard_negative"),
            "easy_negative": kinds.count("easy_negative"),
            "note": "Templated, not collected from real scam traffic. These "
                    "numbers measure the method, not field performance.",
        },
        "held_out": {
            "n": int(len(y_test)),
            "recall_on_scams": round(recall, 3),
            "false_positive_rate_hard_negatives": round(hard_fp, 3),
            "false_positive_rate_easy_negatives": round(easy_fp, 3),
            "roc_auc": round(float(roc_auc_score(y_test, probs)), 4),
            "pr_auc": round(float(average_precision_score(y_test, probs)), 4),
            "threshold": threshold,
            "threshold_chosen_by": f"lowest threshold with <={HARD_FP_BUDGET:.0%} false positives on hard negatives, measured on train",
        },
        "per_pattern_on_full_corpus": per_pattern_report(X, y),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "feature_order": list(FEATURE_ORDER),
        "coefficients": coefficients,
        "intercept": round(float(model.intercept_[0]), 4),
        "threshold": threshold,
        "metrics": metrics,
        "environment": {"python": platform.python_version()},
    }, indent=2) + "\n", encoding="utf-8")

    # ── Report ────────────────────────────────────────────────────────────────
    print(f"\n  corpus: {metrics['corpus']['total']} messages "
          f"({metrics['corpus']['scam']} scam, "
          f"{metrics['corpus']['hard_negative']} hard negative, "
          f"{metrics['corpus']['easy_negative']} easy negative)")

    h = metrics["held_out"]
    print(f"\n  HELD OUT ({h['n']} messages, threshold {h['threshold']})")
    print(f"    recall on scams                      {h['recall_on_scams']:>7.1%}")
    print(f"    false positives on HARD negatives    {h['false_positive_rate_hard_negatives']:>7.1%}   <- the number that matters")
    print(f"    false positives on easy negatives    {h['false_positive_rate_easy_negatives']:>7.1%}")
    print(f"    ROC-AUC {h['roc_auc']}   PR-AUC {h['pr_auc']}")

    print("\n  WHAT THE MODEL LEARNED TO TRUST")
    print("    (weak cues appear in real bank messages too, so a low weight here")
    print("     is the model agreeing that urgency alone proves nothing)")
    weak = {p.code for p in WEAK_PATTERNS}
    for code, coef in sorted(coefficients.items(), key=lambda kv: -kv[1]):
        group = "weak  " if code in weak else "strong"
        print(f"    {group}  {code:20} {coef:>+8.3f}")

    print("\n  PER-PATTERN PRECISION (how often this pattern alone means fraud)")
    for code, row in sorted(
        metrics["per_pattern_on_full_corpus"].items(),
        key=lambda kv: -(kv[1]["precision"] or 0),
    ):
        if row["fires_on"] == 0:
            print(f"    {code:20}   never fires")
            continue
        print(f"    {code:20} {row['precision']:>6.1%}  (fires on {row['fires_on']} messages)")

    print(f"\n  written: {OUT.relative_to(ROOT)}")
    print(f"  {metrics['corpus']['note']}")
    print(f"  The threshold above is a REPORTING threshold. payee_check consumes the")
    print(f"  continuous score, so these recall/FP figures describe this model in")
    print(f"  isolation, not the verdict the product reaches.")


if __name__ == "__main__":
    main()
