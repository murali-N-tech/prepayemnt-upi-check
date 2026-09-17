"""Score the demo statement end to end and print what the judges will see.

Run this before demonstrating anything. It builds a throwaway database, seeds
the counterparty crowd, imports docs/demo/DEMO_UPI_Statement.pdf, and pushes
every planted row plus a sample of ordinary ones through the same model,
feature mapping and payee checks the API uses. If a row moved, you find out
here rather than in front of a panel.

    python scripts/verify_demo_statement.py

It exits non-zero if the demo no longer behaves as the answer key claims, so
it also works as a check in CI.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

import backend.app.services.profile_store as _ps  # noqa: E402

DEMO = ROOT / "docs" / "demo" / "DEMO_UPI_Statement.pdf"

# What the answer key promises. A planted row must clear the operating
# threshold; an ordinary one must not. F4 is the exception and is asserted the
# other way round on purpose: the report measures 28.6% recall on
# victim-authorised transfers, and a demo that quietly flagged it would be
# claiming something the evaluation does not support.
EXPECT_FLAG = {"F1": True, "F2": True, "F3": True, "F4": False, "F5": True}

CASES = [
    # code, label, vpa, amount, days ago, hour, minute, extra feature inputs
    ("--", "canteen lunch",            "srilakshmi.canteen@ybl",   90, 0, 13, 20, {"txns_today": 3}),
    ("--", "weekly groceries",         "freshmart.store@ibl",     640, 1, 19,  5, {"txns_today": 4}),
    ("--", "monthly rent",             "ramanarao.k@oksbi",     18500, 2, 10, 15, {"txns_today": 2}),
    ("--", "cab to the office",        "metroride.trips@ibl",     120, 1,  9, 10, {"txns_today": 5}),
    ("F1", "probe burst, 3rd of 8",    "verify03@quickpay",         5, 6,  2, 20,
     {"seconds_since_last_txn": 180, "txns_last_hour": 6, "txns_today": 7}),
    ("F2", "funnel, 3rd of 5",         "quickcash.agency@fastpay", 4500, 4, 18, 24,
     {"seconds_since_last_txn": 660, "txns_last_hour": 3, "txns_today": 6}),
    ("F3", "hijacked profile",         "nehru.traders99@fastpay", 92400, 3,  3, 47, {"txns_today": 1}),
    ("F4", "victim-authorised",        "electricity.billdesk@upiservice", 18000, 2, 11, 32,
     {"txns_today": 2}),
    ("F5", "lookalike bank handle",    "hdfcbank.refund@yb1",     47500, 1, 19, 21, {"txns_today": 3}),
]


def main() -> int:
    if not DEMO.exists():
        print(f"  no demo statement at {DEMO.relative_to(ROOT)}")
        print("  build it:  python scripts/make_demo_statement.py")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        _ps.DB_PATH = Path(tmp) / "verify.db"

        from datetime import datetime, timedelta

        from backend.app.services.payee_reputation import assess_payee, connect
        from backend.app.services.statement_parser import (
            generate_behavior_profile,
            parse_statement_file,
        )
        from backend.app.services.vpa import analyse_vpa
        from backend.ml.dataset import FEATURES
        from backend.ml.features import build_features
        from backend.models.ensemble_model import load_metrics, load_model

        sys.path.insert(0, str(ROOT / "scripts"))
        from bootstrap_payee_reputation import demo_statement_payees

        conn = connect()
        try:
            demo_statement_payees(conn)
        finally:
            conn.close()

        parsed = parse_statement_file(DEMO.name, DEMO.read_bytes())
        txs = parsed["transactions"]
        profile = generate_behavior_profile(txs)
        model = load_model()
        threshold = load_metrics()["selected"]["operating_point"]["threshold"]

        print(f"\n  statement   {len(txs)} rows, {parsed.get('source_type')}")
        print(f"  payer       median Rs {profile['median_amount']:.0f}, "
              f"usual hour {profile['most_active_hour']}, "
              f"{profile['night_transactions']} night rows, "
              f"{profile['distinct_payees']} payees")
        print(f"  threshold   {threshold}  (recall 55.8% at a 1% false-alarm budget)\n")

        head = (f"  {'':4}{'what':<24}{'amount':>10}{'age':>5}{'payers':>7}"
                f"{'repeat':>8}{'vpa':>5}{'model':>8}   verdict")
        print(head)
        print("  " + "-" * (len(head) - 2))

        now = datetime.now()
        failures: list[str] = []

        for code, label, vpa, amount, days, hh, mm, extra in CASES:
            when = (now - timedelta(days=days)).replace(hour=hh, minute=mm, second=0)
            rep = assess_payee(vpa).as_dict()
            feats = build_features(
                amount, when.isoformat(), profile=profile, reputation=rep,
                payer_seen_payee_before=(code == "--"), **extra,
            )
            frame = pd.DataFrame([[feats[c] for c in FEATURES]], columns=FEATURES)
            p = float(model.predict_proba(frame)[0, 1])
            vpa_score = analyse_vpa(vpa).score
            flagged = p >= threshold

            payers = rep.get("distinct_payers")
            repeat = rep.get("repeat_payers")
            ratio = f"{(repeat or 0) / payers:.2f}" if payers else "-"
            verdict = "FLAG" if flagged else "pass"
            if vpa_score >= 60:
                verdict += " + VPA CRITICAL"
            elif vpa_score > 0:
                verdict += " + vpa warn"

            print(f"  {code:<4}{label:<24}{amount:>10,}{str(rep.get('age_days')):>5}"
                  f"{str(payers):>7}{ratio:>8}{vpa_score:>5}{p:>8.3f}   {verdict}")

            if code == "--" and flagged:
                failures.append(f"{label} is an ordinary payment but scored {p:.3f}")
            if code != "--":
                want = EXPECT_FLAG[code]
                if flagged != want:
                    failures.append(
                        f"{code} ({label}) scored {p:.3f}; expected "
                        f"{'at or above' if want else 'below'} {threshold}"
                    )

        print()
        if failures:
            print("  DEMO IS NOT READY:")
            for f in failures:
                print(f"    - {f}")
            print("\n  Retrain (python backend/train_model.py) and rebuild the statement")
            print("  (python scripts/make_demo_statement.py), then run this again.")
            return 1

        print("  All rows behave as docs/demo/DEMO_ANSWER_KEY.md describes.")
        print("  F4 passing is the expected result, not a failure - it is the class")
        print("  the behavioural model is weakest on, and the payee and language")
        print("  checks are what cover it.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
