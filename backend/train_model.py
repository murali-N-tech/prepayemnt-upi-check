"""Train and honestly evaluate the transaction risk classifier.

What changed and why
--------------------
This script used to build 2,000 rows of np.random.uniform and label them with
a hand-written rule (amount > 80000 | rolling_txn_count > 7 | time_gap < 50).
A model fitted on that can only relearn the rule it was handed, over features
that carry no signal because they were drawn independently of the label. It
reported nothing, and no accuracy figure from it meant anything.

It now trains on backend/ml/dataset.py, where labels come from the generative
process rather than a rule over the features, and reports the metrics that
matter for a fraud problem:

  PR-AUC                 not accuracy. At a ~1% base rate a model that always
                         says "legitimate" is 99% accurate and useless.
  recall at a fixed FPR  the operating question: of the fraud out there, how
                         much do we catch while alarming on 1 in 100 good
                         payments? A fraud system's cost is false positives.
  per-scenario recall    social engineering is the hard case and the one this
                         project exists for; an average hides it.

The data is SIMULATED. There is no public labelled UPI fraud dataset. The
numbers below describe the method, not field performance, and the report says
so. To train on real data, produce a DataFrame with the columns in
backend/ml/dataset.FEATURES plus is_fraud, and pass it to train().

    python backend/train_model.py
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sklearn.calibration import CalibratedClassifierCV  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import train_test_split  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

import joblib  # noqa: E402
import scipy  # noqa: E402
import sklearn  # noqa: E402

from backend.ml.dataset import (  # noqa: E402
    FEATURES,
    LABEL,
    PAYEE_FEATURES,
    PAYER_FEATURES,
    generate,
)

MODELS = ROOT / "models"
FPR_BUDGET = 0.01          # alarm on at most 1 in 100 legitimate payments


def recall_at_fpr(y_true: np.ndarray, scores: np.ndarray, budget: float) -> tuple[float, float]:
    """Recall achievable while staying inside a false-positive budget, and the
    threshold that achieves it."""
    fpr, tpr, thresholds = roc_curve(y_true, scores)
    ok = fpr <= budget
    if not ok.any():
        return 0.0, 1.0
    i = int(np.argmax(tpr * ok))
    return float(tpr[i]), float(thresholds[i])


def _fit_and_score(
    name: str,
    estimator,
    X_train, y_train, X_test, y_test, scen_test,
) -> dict:
    model = CalibratedClassifierCV(estimator, method="isotonic", cv=5)
    model.fit(X_train, y_train)
    probs = model.predict_proba(X_test)[:, 1]

    recall, threshold = recall_at_fpr(y_test, probs, FPR_BUDGET)
    flagged = probs >= threshold

    per_scenario = {}
    for scenario in sorted(set(scen_test)):
        if scenario == "legitimate":
            continue
        mask = (scen_test == scenario).to_numpy()
        if mask.sum():
            per_scenario[scenario] = {
                "n": int(mask.sum()),
                "recall": round(float(flagged[mask].mean()), 4),
            }

    return {
        "model": name,
        "roc_auc": round(float(roc_auc_score(y_test, probs)), 4),
        "pr_auc": round(float(average_precision_score(y_test, probs)), 4),
        "brier": round(float(brier_score_loss(y_test, probs)), 5),
        "operating_point": {
            "fpr_budget": FPR_BUDGET,
            "threshold": round(float(threshold), 4),
            "recall": round(float(recall), 4),
            "precision": round(
                float((y_test[flagged] == 1).mean()) if flagged.any() else 0.0, 4
            ),
        },
        "recall_by_scenario": per_scenario,
        "_model": model,
    }


def train(df: pd.DataFrame | None = None, seed: int = 42) -> dict:
    df = generate(seed=seed) if df is None else df
    y = df[LABEL].to_numpy()
    scen = df.get("scenario", pd.Series(["?"] * len(df)))

    # Stratified: with ~1% positives an unstratified split can leave the test
    # set with almost no fraud in it.
    idx_train, idx_test = train_test_split(
        np.arange(len(df)), test_size=0.30, random_state=seed, stratify=y
    )
    y_train, y_test = y[idx_train], y[idx_test]
    scen_test = scen.iloc[idx_test]

    def subset(cols):
        return df[cols].iloc[idx_train], df[cols].iloc[idx_test]

    linear = lambda: Pipeline([                                    # noqa: E731
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])
    boosted = lambda: HistGradientBoostingClassifier(              # noqa: E731
        max_iter=300, learning_rate=0.08, max_leaf_nodes=31,
        class_weight="balanced", random_state=seed,
    )

    X_train, X_test = subset(FEATURES)
    baseline = _fit_and_score("LogisticRegression (balanced)", linear(),
                              X_train, y_train, X_test, y_test, scen_test)
    best = _fit_and_score("HistGradientBoosting (balanced)", boosted(),
                          X_train, y_train, X_test, y_test, scen_test)

    # ── Ablation ─────────────────────────────────────────────────────────
    # The project's claim is that scoring the payer is not enough, because in
    # social engineering the payer is behaving normally by definition. This
    # measures it rather than asserting it.
    Xp_train, Xp_test = subset(PAYER_FEATURES)
    payer_only = _fit_and_score("payer features only", boosted(),
                                Xp_train, y_train, Xp_test, y_test, scen_test)
    Xq_train, Xq_test = subset(PAYEE_FEATURES)
    payee_only = _fit_and_score("payee features only", boosted(),
                                Xq_train, y_train, Xq_test, y_test, scen_test)

    # Unsupervised half, fitted on legitimate traffic only. An anomaly
    # detector should model normal, not a mixture of normal and fraud.
    iso = Pipeline([
        ("scale", StandardScaler()),
        ("iso", IsolationForest(contamination=0.02, random_state=seed, n_estimators=200)),
    ])
    iso.fit(X_train[y_train == 0])
    iso_scores = -iso.named_steps["iso"].score_samples(
        iso.named_steps["scale"].transform(X_test)
    )

    MODELS.mkdir(exist_ok=True)
    joblib.dump(best.pop("_model"), MODELS / "risk_model.pkl")
    # SHAP needs a background distribution. np.random.rand() was being used,
    # which explains a prediction against noise rather than against normal
    # traffic, so the attributions meant nothing.
    background = df.loc[idx_train, FEATURES].sample(
        n=min(200, len(idx_train)), random_state=seed
    )
    background.to_json(MODELS / "shap_background.json", orient="split", index=False)
    joblib.dump(iso, MODELS / "isolation_forest.pkl")
    for d in (baseline, payer_only, payee_only):
        d.pop("_model", None)

    def se(d):
        return d["recall_by_scenario"].get("social_engineering", {}).get("recall", 0.0)

    metrics = {
        # Recorded so a load failure elsewhere can say what changed. A pickle
        # is tied to the versions that produced it.
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit-learn": sklearn.__version__,
            "scipy": scipy.__version__,
            "joblib": joblib.__version__,
        },
        "data": {
            "source": "simulated (backend/ml/dataset.py)",
            "caveat": (
                "No public labelled UPI fraud dataset exists. These figures "
                "describe the method on simulated data, not field performance."
            ),
            "rows": int(len(df)),
            "fraud_rate": round(float(y.mean()), 5),
            "test_rows": int(len(y_test)),
            "test_fraud": int(y_test.sum()),
        },
        "baseline": baseline,
        "selected": best,
        "ablation": {
            "question": (
                "Can a model that sees only the payer's own behaviour catch "
                "fraud the payer authorised themselves?"
            ),
            "payer_features_only": payer_only,
            "payee_features_only": payee_only,
            "all_features": {
                k: best[k] for k in ("roc_auc", "pr_auc", "operating_point", "recall_by_scenario")
            },
            "social_engineering_recall": {
                "payer_only": se(payer_only),
                "payee_only": se(payee_only),
                "both": se(best),
            },
        },
        "unsupervised": {
            "model": "IsolationForest fitted on legitimate traffic only",
            "roc_auc": round(float(roc_auc_score(y_test, iso_scores)), 4),
        },
        "features": {"all": FEATURES, "payer": PAYER_FEATURES, "payee": PAYEE_FEATURES},
    }

    (MODELS / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def _print(m: dict) -> None:
    d = m["data"]
    print(f"\n  data      {d['rows']:,} rows, {d['fraud_rate']:.2%} fraud ({d['source']})")
    print(f"            test set {d['test_rows']:,} rows, {d['test_fraud']} fraud\n")

    print(f"  {'model':34} {'ROC-AUC':>8} {'PR-AUC':>8} {'recall@1%FPR':>13} {'precision':>10}")
    for d2 in (m["baseline"], m["selected"]):
        op = d2["operating_point"]
        print(f"  {d2['model']:34} {d2['roc_auc']:>8} {d2['pr_auc']:>8} "
              f"{op['recall']:>12.1%} {op['precision']:>10.1%}")

    print("\n  ROC-AUC looks strong and PR-AUC does not. At a 1% base rate that gap")
    print("  is the point: accuracy and ROC-AUC flatter a fraud model badly.\n")

    sel = m["selected"]
    print("  Recall by scenario, selected model, at the 1% false-positive budget:")
    for name, v in sorted(sel["recall_by_scenario"].items(), key=lambda kv: -kv[1]["n"]):
        print(f"    {name:22} {v['recall']:>6.1%}   (n={v['n']})")

    ab = m["ablation"]["social_engineering_recall"]
    print("\n  ABLATION - social engineering recall, the case this project exists for:")
    print(f"    payer behaviour only   {ab['payer_only']:>6.1%}")
    print(f"    payee signals only     {ab['payee_only']:>6.1%}")
    print(f"    both                   {ab['both']:>6.1%}")
    print("    The payer is behaving normally by definition, so the payer-side")
    print("    model cannot see it. That is the argument for the payee check.")

    print(f"\n  IsolationForest ROC-AUC {m['unsupervised']['roc_auc']}")
    print(f"\n  {d['caveat']}")
    print("\n  written: models/metrics.json, models/risk_model.pkl, models/isolation_forest.pkl")


if __name__ == "__main__":
    _print(train())
