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
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

import joblib  # noqa: E402
import scipy  # noqa: E402
import sklearn  # noqa: E402

from backend.ml.dataset import (  # noqa: E402
    FEATURES,
    availability_bias,
    LABEL,
    PAYEE_FEATURES,
    PAYER_FEATURES,
    generate,
)

MODELS = ROOT / "models"
FPR_BUDGET = 0.01          # alarm on at most 1 in 100 legitimate payments


def _brier_of_constant(y_true: np.ndarray) -> float:
    """Brier score of always predicting the base rate - the reference any
    probabilistic model has to beat before its calibration means anything."""
    rate = float(np.mean(y_true))
    return float(np.mean((y_true - rate) ** 2))


def _brier_skill(y_true: np.ndarray, probs: np.ndarray) -> float:
    ref = _brier_of_constant(y_true)
    if ref == 0.0:
        return 0.0
    return 1.0 - float(brier_score_loss(y_true, probs)) / ref


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
    X_train, y_train, X_val, y_val, X_test, y_test, scen_test,
) -> dict:
    model = CalibratedClassifierCV(estimator, method="isotonic", cv=5)
    model.fit(X_train, y_train)

    # The operating threshold is CHOSEN on validation and MEASURED on test.
    # Previously both came from the test set: recall_at_fpr searched the test
    # ROC curve for the threshold that maximised recall inside the budget, and
    # then the recall and precision at that threshold were reported on the same
    # rows. That is selection on the evaluation set - it reports the best of
    # ~n_test thresholds as if it were an unbiased estimate, and the false
    # positive rate it promises is the one that cannot be exceeded on the only
    # data it was checked against.
    val_probs = model.predict_proba(X_val)[:, 1]
    _, threshold = recall_at_fpr(y_val, val_probs, FPR_BUDGET)

    probs = model.predict_proba(X_test)[:, 1]
    flagged = probs >= threshold
    recall = float(flagged[y_test == 1].mean()) if (y_test == 1).any() else 0.0
    # What the budget actually bought on held-out data, which is the number
    # that matters and was previously unreportable.
    realised_fpr = float(flagged[y_test == 0].mean()) if (y_test == 0).any() else 0.0

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
        # A Brier score is meaningless without something to compare it to. At a
        # 1.2% base rate, always predicting the base rate scores about 0.0119,
        # so a bare "brier: 0.009" reads like a good number when it may be
        # barely better than predicting the prior. The skill score is the
        # fraction of that reference error removed: 0 is no better than the
        # prior, 1 is perfect, negative is worse than the prior.
        "brier_baseline_rate": round(float(_brier_of_constant(y_test)), 5),
        "brier_skill_score": round(float(_brier_skill(y_test, probs)), 4),
        "operating_point": {
            "fpr_budget": FPR_BUDGET,
            # Chosen on validation, so this is a real out-of-sample operating
            # point rather than the best threshold found on the test set.
            "threshold": round(float(threshold), 4),
            "threshold_selected_on": "validation split",
            "recall": round(float(recall), 4),
            "realised_fpr": round(realised_fpr, 4),
            "precision": round(
                float((y_test[flagged] == 1).mean()) if flagged.any() else 0.0, 4
            ),
        },
        "recall_by_scenario": per_scenario,
        "_model": model,
    }


def _strip_fit_only_rng(model, _seen: set[int] | None = None) -> int:
    """Remove numpy Generator objects from a fitted estimator before it is dumped.

    scikit-learn leaves a ``np.random.Generator`` on a fitted
    HistGradientBoostingClassifier (``_feature_subsample_rng``). It is used
    only while fitting; predict never touches it. But it pickles as a PCG64
    bit generator, and numpy changed how bit generators pickle between 1.x and
    2.x, so a model trained under numpy 2 fails to load under numpy 1 with:

        <class 'numpy.random._pcg64.PCG64'> is not a known BitGenerator module

    That is the whole failure: nothing about the trained weights is version
    specific, only this leftover RNG. Dropping it makes the artifact load
    across numpy majors, which matters here because training and serving are
    not always the same interpreter.

    Returns the number of attributes removed.
    """
    if _seen is None:
        _seen = set()
    if id(model) in _seen:
        return 0
    _seen.add(id(model))

    removed = 0
    container = getattr(model, "__dict__", None)
    if isinstance(container, dict):
        items = list(container.items())
    elif isinstance(model, dict):
        items = list(model.items())
    elif isinstance(model, (list, tuple)):
        items = list(enumerate(model))
    else:
        return 0

    for key, value in items:
        if isinstance(value, np.random.Generator):
            if isinstance(container, dict):
                del container[key]
            elif isinstance(model, dict):
                del model[key]
            removed += 1
        else:
            removed += _strip_fit_only_rng(value, _seen)
    return removed


def train(df: pd.DataFrame | None = None, seed: int = 42) -> dict:
    df = generate(seed=seed) if df is None else df
    y = df[LABEL].to_numpy()
    scen = df.get("scenario", pd.Series(["?"] * len(df)))

    # Three splits, not two. Stratified throughout: with ~1% positives an
    # unstratified split can leave a fold with almost no fraud in it.
    #   train      fits the model
    #   validation picks the operating threshold
    #   test       is measured once, and never looked at while choosing anything
    idx_fit, idx_test = train_test_split(
        np.arange(len(df)), test_size=0.25, random_state=seed, stratify=y
    )
    idx_train, idx_val = train_test_split(
        idx_fit, test_size=0.20, random_state=seed, stratify=y[idx_fit]
    )
    y_train, y_val, y_test = y[idx_train], y[idx_val], y[idx_test]
    scen_test = scen.iloc[idx_test]

    def subset(cols):
        return df[cols].iloc[idx_train], df[cols].iloc[idx_val], df[cols].iloc[idx_test]

    # The payee-history features are NaN wherever the deployment would not
    # have observed the payee (dataset.apply_observation_mask). Only the
    # boosted model reads NaN natively; the linear baseline and the anomaly
    # detector need it filled in, so they get the standard remedy, a median
    # imputer. That handicap is not an accident of implementation - it is part
    # of what the comparison measures. A linear model cannot represent "this
    # value is absent" at all, so it has to be told the payee is average, and
    # being told the payee is average is exactly the failure this whole change
    # set exists to remove.
    impute = lambda: SimpleImputer(strategy="median")               # noqa: E731

    linear = lambda: Pipeline([                                    # noqa: E731
        ("impute", impute()),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])
    boosted = lambda: HistGradientBoostingClassifier(              # noqa: E731
        max_iter=300, learning_rate=0.08, max_leaf_nodes=31,
        class_weight="balanced", random_state=seed,
    )

    X_train, X_val, X_test = subset(FEATURES)
    baseline = _fit_and_score("LogisticRegression (balanced)", linear(),
                              X_train, y_train, X_val, y_val, X_test, y_test, scen_test)
    best = _fit_and_score("HistGradientBoosting (balanced)", boosted(),
                          X_train, y_train, X_val, y_val, X_test, y_test, scen_test)

    # ── Ablation ─────────────────────────────────────────────────────────
    # The project's claim is that scoring the payer is not enough, because in
    # social engineering the payer is behaving normally by definition. This
    # measures it rather than asserting it.
    Xp_train, Xp_val, Xp_test = subset(PAYER_FEATURES)
    payer_only = _fit_and_score("payer features only", boosted(),
                                Xp_train, y_train, Xp_val, y_val, Xp_test, y_test, scen_test)
    Xq_train, Xq_val, Xq_test = subset(PAYEE_FEATURES)
    payee_only = _fit_and_score("payee features only", boosted(),
                                Xq_train, y_train, Xq_val, y_val, Xq_test, y_test, scen_test)

    # Unsupervised half, fitted on legitimate traffic only. An anomaly
    # detector should model normal, not a mixture of normal and fraud.
    iso = Pipeline([
        ("impute", impute()),
        ("scale", StandardScaler()),
        ("iso", IsolationForest(contamination=0.02, random_state=seed, n_estimators=200)),
    ])
    iso.fit(X_train[y_train == 0])
    iso_scores = -iso.named_steps["iso"].score_samples(
        iso.named_steps["scale"].transform(iso.named_steps["impute"].transform(X_test))
    )

    MODELS.mkdir(exist_ok=True)
    selected_model = best.pop("_model")
    stripped = _strip_fit_only_rng(selected_model)
    joblib.dump(selected_model, MODELS / "risk_model.pkl")
    # SHAP needs a background distribution. np.random.rand() was being used,
    # which explains a prediction against noise rather than against normal
    # traffic, so the attributions meant nothing.
    background = df.loc[idx_train, FEATURES].sample(
        n=min(200, len(idx_train)), random_state=seed
    )
    background.to_json(MODELS / "shap_background.json", orient="split", index=False)
    stripped += _strip_fit_only_rng(iso)
    joblib.dump(iso, MODELS / "isolation_forest.pkl")
    if stripped:
        print(f"  stripped {stripped} fit-only RNG attribute(s) so the pickle "
              "loads across numpy versions")
    for d in (baseline, payer_only, payee_only):
        d.pop("_model", None)

    def se(d):
        return d["recall_by_scenario"].get("social_engineering", {}).get("recall", 0.0)

    hidden = df["payee_history_available"] == 0.0
    bias = availability_bias(df)

    metrics = {
        # Whether the observation mask leaked the label. If the model can tell
        # fraud from "we have no payee history" alone, it will warn on every
        # genuine first payment to a stranger, and the availability work has
        # made things worse rather than better.
        "evidence_availability": {
            "payee_history_hidden_rows": int(hidden.sum()),
            "payee_history_hidden_share": round(float(hidden.mean()), 4),
            "fraud_rate_when_hidden": round(float(df.loc[hidden, LABEL].mean()), 5),
            "fraud_rate_when_available": round(float(df.loc[~hidden, LABEL].mean()), 5),
            "availability_bias": round(bias, 5),
            "reading": (
                "Positive bias means an unobserved payee is somewhat more "
                "likely to be fraudulent, which is true of the world and is "
                "why the payee features are withheld rather than guessed. It "
                "must stay small: a large value would mean the model can use "
                "'unknown' as a proxy for 'fraud'."
            ),
        },
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
            "train_rows": int(len(y_train)),
            "val_rows": int(len(y_val)),
            "test_rows": int(len(y_test)),
            "test_fraud": int(y_test.sum()),
        },
        "baseline": baseline,
        "selected": best,
        "ablation": {
            "question": (
                "How much of the payer-authorised fraud (social engineering) "
                "does each half of the feature set catch on its own, and how "
                "much does using both add over the better half?"
            ),
            "caveat": (
                "In this simulator a social-engineering payment is often well "
                "above the victim's usual amount - half the scenarios draw a "
                "multiple around 10x - because real scam amounts are sometimes "
                "large. So the payer half is NOT blind to this case here, and "
                "the original claim that it cannot see social engineering at "
                "all is not supported. What the numbers do support is the "
                "combined lift below."
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
                # The defensible headline. Not "the payer half sees nothing" -
                # on this simulator it sees a fair amount, mostly through the
                # amount - but how much the two halves together add over the
                # better half alone. That is what the payee check buys.
                "lift_over_better_half": round(
                    se(best) - max(se(payer_only), se(payee_only)), 4
                ),
                "reading": (
                    "Report the combined model against the better single half. "
                    "Whichever half wins on a given run, neither alone reaches "
                    "what both reach together."
                ),
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

    sel0 = m["selected"]
    if sel0["roc_auc"] - sel0["pr_auc"] > 0.15:
        print("\n  ROC-AUC looks strong and PR-AUC does not. At a 1% base rate that gap")
        print("  is the point: accuracy and ROC-AUC flatter a fraud model badly.")
    print(f"  Brier {sel0['brier']} against {sel0['brier_baseline_rate']} for always "
          f"predicting the base rate")
    print(f"  -> skill score {sel0['brier_skill_score']:+.3f} "
          f"({'better' if sel0['brier_skill_score'] > 0 else 'NO better'} than the prior)\n")

    sel = m["selected"]
    print("  Recall by scenario, selected model, at the 1% false-positive budget:")
    for name, v in sorted(sel["recall_by_scenario"].items(), key=lambda kv: -kv[1]["n"]):
        print(f"    {name:22} {v['recall']:>6.1%}   (n={v['n']})")

    ab = m["ablation"]["social_engineering_recall"]
    print("\n  ABLATION - social engineering recall, the case this project exists for:")
    print(f"    payer behaviour only   {ab['payer_only']:>6.1%}")
    print(f"    payee signals only     {ab['payee_only']:>6.1%}")
    print(f"    both                   {ab['both']:>6.1%}")
    # This used to print the conclusion unconditionally, whatever the three
    # numbers above it said - so a run where the payer-only model did BETTER
    # than the payee-only one still printed "the payer-side model cannot see
    # it". Read the numbers instead of asserting over them.
    margin = ab["payee_only"] - ab["payer_only"]
    if margin > 0.05:
        print(f"    The payee half catches {margin:.0%} more of it than the payer half.")
        print("    The payer is behaving normally by definition, so a payer-side")
        print("    model cannot see this case. That is the argument for the payee check.")
    elif margin < -0.05:
        print("    NOTE: the payer half did better than the payee half here, which is")
        print("    the opposite of this project's claim. Do not report the claim as")
        print("    supported - check the simulator's social_engineering generator.")
    else:
        print("    The two halves are within 5 points of each other, so this run does")
        print("    not separate them. The combined model is what to report.")
    if ab["both"] < max(ab["payer_only"], ab["payee_only"]) - 0.02:
        print("    WARNING: the combined model is worse than its better half.")
    print(f"    Combined lift over the better half: "
          f"{ab['lift_over_better_half']:+.1%}  <- the claim to report")

    print(f"\n  IsolationForest ROC-AUC {m['unsupervised']['roc_auc']}")
    print(f"\n  {d['caveat']}")
    print("\n  written: models/metrics.json, models/risk_model.pkl, models/isolation_forest.pkl")


if __name__ == "__main__":
    _print(train())
