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

# What the answer key promises, judged on the SYSTEM verdict rather than on
# the ML probability alone.
#
# The first version of this script checked only whether the model cleared its
# threshold, and then declared the demo broken when F3 did not. That was the
# same error the project's whole architecture argues against: reading one
# evidence family as though it were the system. The model is blind to a
# payee's address, weak wherever the payer behaves normally, and explicitly
# not expected to carry every case - that is why there are ten other families
# and a combination rule. A verifier that grades the demo on the model alone
# grades the wrong thing.
#
# F4 stays False on purpose. It is the victim-authorised transfer, the class
# the report measures lowest recall on, and a demo that quietly flagged it
# would be claiming something the evaluation does not support.
# Two expectations per planted row, because the model and the assembled
# verdict are different things and the project's whole argument is about where
# they differ.
#
#   model   does the calibrated classifier clear its operating threshold?
#   system  what does check_payee return once the deterministic families have
#           had their say?
#
# F4 is the case worth pausing on. The model scores it at 0.077 and does not
# flag it - which is correct, and is the 19-20% recall the report measures on
# victim-authorised transfers. The system still returns WARN, because the
# payee is four days old with nine payers and none of them returning. That is
# not the demo compensating for a weak model; it is the reason the payee check
# exists, visible in one row.
#
# F1 is the mirror image. A five-rupee payment to an unknown address carries
# nothing a deterministic check can see; the burst lives entirely in velocity,
# which only the classifier reads. While the classifier sat outside the
# assembly - run separately in main.py and reconciled afterwards - this row
# scored 0.261 on the model and still came back APPROVE, because the model's
# reading never reached the combination rule. It is a family now, and the row
# reaches STEP_UP on the strength of it.
EXPECT = {
    "F1": {"model": True,  "system": True},
    "F2": {"model": True,  "system": True},
    "F3": {"model": False, "system": True},
    "F4": {"model": False, "system": True},
    "F5": {"model": True,  "system": True},
}

NON_APPROVE = {"WARN", "STEP_UP", "BLOCK"}

def velocity_from_statement(txs, when):
    """Compute the velocity features from the statement, not by hand.

    The first version of this script carried hand-written velocity inputs per
    case, which is how a demo quietly becomes a fiction: the numbers drift
    towards whatever makes the row score, and the verifier ends up confirming
    the tuning rather than the system. These come from the rows themselves, so
    the only way to change them is to change the statement.
    """
    from datetime import timedelta

    stamps = sorted(
        t["timestamp"] for t in txs
        if t.get("timestamp") and str(t.get("txn_type") or "DEBIT").upper() == "DEBIT"
    )
    stamps = [pd.to_datetime(s) for s in stamps]
    here = pd.to_datetime(when)

    earlier = [s for s in stamps if s < here]
    gap = (here - earlier[-1]).total_seconds() if earlier else 9000.0
    last_hour = sum(1 for s in earlier if here - s <= timedelta(hours=1))
    today = sum(1 for s in stamps if s.date() == here.date())
    return {
        "seconds_since_last_txn": float(max(gap, 1.0)),
        "txns_last_hour": float(last_hour),
        "txns_today": float(max(today, 1)),
    }


CASES = [
    # code, label, vpa, amount, days ago, hour, minute, extra feature inputs
    ("--", "canteen lunch",            "srilakshmi.canteen@ybl",   90, 0, 13, 20, {}),
    ("--", "weekly groceries",         "freshmart.store@ibl",     640, 1, 19,  5, {}),
    ("--", "monthly rent",             "ramanarao.k@oksbi",     18500, 2, 10, 15, {}),
    ("--", "cab to the office",        "metroride.trips@ibl",     120, 1,  9, 10, {}),
    ("F1", "probe burst, 3rd of 8",    "verify03@quickpay",         5, 6,  2, 20,
     {}),
    ("F2", "funnel, 3rd of 5",         "quickcash.agency@fastpay", 4500, 4, 18, 24,
     {}),
    # Second of three transfers inside eleven minutes. The velocity inputs are
    # the scenario, not decoration: training's account_takeover rows sit at a
    # median inter-arrival of 81 seconds. Scored as an isolated payment with a
    # two-hour gap, this case does not resemble a takeover and should not be
    # expected to score as one.
    ("F3", "hijacked profile, 2nd of 3",  "nehru.traders99@fastpay", 92400, 3,  3, 52,
     {}),
    ("F4", "victim-authorised",        "electricity.billdesk@upiservice", 18000, 2, 11, 32,
     {"txns_today": 2}),
    ("F5", "lookalike bank handle",    "hdfcbank.refund@yb1",     47500, 1, 19, 21, {}),
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
        from backend.app.services.payee_check import check_payee
        from backend.app.services.vpa import analyse_vpa
        from backend.ml.dataset import FEATURES
        from backend.ml.features import build_features, build_vector
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
        # The payer-behaviour family compares against this payer's own rows, so
        # the statement is the history as well as the source of the profile.
        history = pd.DataFrame([
            {"timestamp": t.get("timestamp"), "amount": t.get("amount"),
             "merchant": t.get("merchant") or "", "upi_id": t.get("upi_id") or ""}
            for t in txs
        ])
        model = load_model()
        threshold = load_metrics()["selected"]["operating_point"]["threshold"]

        print(f"\n  statement   {len(txs)} rows, {parsed.get('source_type')}")
        print(f"  payer       median Rs {profile['median_amount']:.0f}, "
              f"usual hour {profile['most_active_hour']}, "
              f"{profile['night_transactions']} night rows, "
              f"{profile['distinct_payees']} payees")
        print(f"  threshold   {threshold}  (model operating point, 1% false-alarm budget)\n")

        head = (f"  {'':4}{'what':<24}{'amount':>9}{'ml p':>8}{'ml':>5}"
                f"{'risk':>7}{'conf':>6}{'evidence':>9}   verdict")
        print(head)
        print("  " + "-" * (len(head) - 2))

        now = datetime.now()
        failures: list[str] = []

        for code, label, vpa, amount, days, hh, mm, extra in CASES:
            when = (now - timedelta(days=days)).replace(hour=hh, minute=mm, second=0)
            rep = assess_payee(vpa).as_dict()
            derived = velocity_from_statement(txs, when)
            derived.update(extra)          # explicit overrides, if any remain
            vpa_score = analyse_vpa(vpa).score

            # The whole assembly, which is what a judge will actually see, and
            # the ONLY scoring path used here. The model is not run separately
            # and compared - it is one family inside this call, and the number
            # printed in the `model` column is read back out of the result.
            assembled = check_payee(
                vpa, payer_id="demo_payer", amount=float(amount), conn=connect(),
                profile=profile, history=history, timestamp=when.isoformat(),
                velocity=derived,
            )
            verdict = assembled["verdict"]
            system_score = assembled["risk_score"]
            confidence = assembled["confidence_score"]
            level = assembled["evidence_level"]
            flagged = verdict in NON_APPROVE
            ml = assembled.get("ml", {})
            ml_available = bool(ml.get("available"))
            p = float(ml.get("probability") or 0.0)
            ml_score = ml.get("score")

            payers = rep.get("distinct_payers")
            carried = "model" if (ml_available and p >= threshold) else (
                "vpa" if vpa_score >= 60 else "other families")
            note = verdict if not flagged else f"{verdict}  (carried by {carried})"

            ml_cell = f"{p:.3f}" if ml_available else "n/a"
            print(f"  {code:<4}{label:<24}{amount:>9,}{ml_cell:>8}{str(ml_score):>5}"
                  f"{system_score:>7}{confidence:>6}{level:>9}   {note}")

            if code == "--":
                if flagged:
                    failures.append(
                        f"{label} is an ordinary payment but the system returned {verdict}"
                    )
                if p >= threshold:
                    failures.append(
                        f"{label} is an ordinary payment but the model scored {p:.3f}"
                    )
                continue

            want = EXPECT[code]
            if not ml_available:
                failures.append(
                    f"{code} ({label}): the ML family reported itself unavailable "
                    f"({ml.get('message')}) - every planted row should be scoreable"
                )
            elif (p >= threshold) != want["model"]:
                failures.append(
                    f"{code} ({label}): model scored {p:.3f}, expected "
                    f"{'at or above' if want['model'] else 'below'} {threshold}"
                )
            if flagged != want["system"]:
                failures.append(
                    f"{code} ({label}): system returned {verdict} at score "
                    f"{system_score}, expected "
                    f"{'a warning or stronger' if want['system'] else 'APPROVE'}"
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
        print()
        print("  Read the two score columns against each other. F3 and F4 are caught")
        print("  with the model scoring them near zero, and F1 is caught by the model")
        print("  while the deterministic families see nothing. That spread is the")
        print("  system's argument for itself: no family covers every case, and the")
        print("  ones that miss are not the ones that catch.")
        print("  F4 passing is the expected result, not a failure - it is the class")
        print("  the behavioural model is weakest on, and the payee and language")
        print("  checks are what cover it.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
