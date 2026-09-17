"""Seed the payee reputation store from statement history already on disk.

Every debit in statement_transactions is one payer paying one payee, which is
exactly the edge the reputation store is built from. Running this turns the
statements users have already uploaded into a working reputation graph.

    python scripts/bootstrap_payee_reputation.py            # from real history
    python scripts/bootstrap_payee_reputation.py --reset    # rebuild from scratch
    python scripts/bootstrap_payee_reputation.py --with-demo-payees
    python scripts/bootstrap_payee_reputation.py --demo-statement

--with-demo-payees additionally inserts four clearly named demo-*@* addresses
that exhibit the patterns the detector looks for. They exist so the feature
can be demonstrated without waiting for a real mule to show up; every one of
them is prefixed `demo-` and can be removed with --reset.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend.app.services.profile_store as _ps  # noqa: E402
from backend.app.services.payee_reputation import (  # noqa: E402
    connect,
    payee_key,
    record_payment,
    report_payee,
)


def bootstrap(conn, reset: bool) -> None:
    if reset:
        with conn:
            conn.execute("DELETE FROM payee_reputation")
            conn.execute("DELETE FROM payee_payers")
            conn.execute("DELETE FROM payee_reports")
        print("  cleared existing reputation data")

    rows = conn.execute(
        """
        SELECT user_id, upi_id, merchant, amount, timestamp
        FROM statement_transactions
        WHERE UPPER(COALESCE(txn_type, 'DEBIT')) = 'DEBIT' AND amount > 0
        ORDER BY COALESCE(timestamp, created_at)
        """
    ).fetchall()

    # One transaction for the whole load: a commit per payment is thousands
    # of fsyncs, which fails outright on a network-mounted database file.
    seen = 0
    conn.execute("BEGIN")
    try:
        for r in rows:
            key = payee_key(r["upi_id"], r["merchant"])
            if not key:
                continue
            record_payment(
                vpa=key,
                payer_id=r["user_id"],
                amount=r["amount"],
                at=r["timestamp"],
                display_name=r["merchant"],
                conn=conn,
                autocommit=False,
            )
            seen += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    payees = conn.execute("SELECT COUNT(*) FROM payee_reputation").fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM payee_payers").fetchone()[0]
    print(f"  {seen:,} payments -> {payees:,} payees, {edges:,} payer-payee edges")


def demo_payees(conn) -> None:
    """Four synthetic payees, each showing one pattern the detector looks for."""
    now = datetime.now(timezone.utc)

    def at(days_ago: float) -> str:
        return (now - timedelta(days=days_ago)).isoformat()

    # 1. Collection account: 9 days old, 24 one-time payers.
    conn.execute("BEGIN")
    for i in range(24):
        record_payment("demo-mule@ybl", f"demo_payer_{i}", 4999 + (i % 3),
                       at(9 - i * 0.3), "Quick Refund Service", conn=conn, autocommit=False)

    # 2. Fixed-fee scam: 30 payers, all paying almost the same amount.
    for i in range(30):
        record_payment("demo-fee-collect@okaxis", f"demo_payer_{100 + i}", 1500 + (i % 2) * 10,
                       at(20 - i * 0.5), "Processing Fee", conn=conn, autocommit=False)

    # 3. Reported address.
    for i in range(6):
        record_payment("demo-reported@paytm", f"demo_payer_{200 + i}", 2500, at(15 - i),
                       "Lottery Claim", conn=conn, autocommit=False)
    conn.commit()
    for i in range(4):
        report_payee("demo-reported@paytm", f"demo_reporter_{i}", "never received the goods")

    # 4. Established merchant: 2 years, many repeat customers.
    conn.execute("BEGIN")
    for i in range(120):
        record_payment("demo-chaipoint@okhdfcbank", f"demo_payer_{300 + (i % 18)}",
                       40 + (i % 7) * 15, at(700 - i * 5), "Chai Point", conn=conn,
                       autocommit=False)
    conn.commit()

    print("  inserted 4 demo payees (demo-mule, demo-fee-collect, demo-reported, demo-chaipoint)")


def demo_statement_payees(conn) -> None:
    """Lay down the crowd around the payees in the demo statement.

    An imported statement is one payer's side of every edge. It cannot say how
    many OTHER people have paid an address or whether any of them came back,
    and those are the two facts that separate a busy shop from a collection
    account. Without this the funnel account in the demo scores like an
    ordinary new payee, because from a single statement that is all it is.

    The spec lives beside the statement in docs/demo/DEMO_PAYEE_SEED.json so
    the two cannot drift; regenerate both with scripts/make_demo_statement.py.
    """
    spec_path = ROOT / "docs" / "demo" / "DEMO_PAYEE_SEED.json"
    if not spec_path.exists():
        print(f"  no seed at {spec_path.relative_to(ROOT)} - run "
              "python scripts/make_demo_statement.py first")
        return

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    payments = 0

    conn.execute("BEGIN")
    try:
        for entry in spec["payees"]:
            age = float(entry["age_days"])
            payers = int(entry["other_payers"])
            each = int(entry["payments_each"])
            amount = float(entry["typical_amount"])
            vpa = entry["vpa"]
            # Spread each payer's visits across the address's life. A payee
            # whose payments all land at once looks like a burst even when it
            # is a two-year-old shop, so the timestamps have to be plausible.
            for i in range(payers):
                for j in range(each):
                    offset = age * (1 - (i * each + j) / max(payers * each, 1))
                    record_payment(
                        vpa=vpa,
                        payer_id=f"demo_crowd_{abs(hash(vpa)) % 9973}_{i}",
                        amount=amount * (0.85 + 0.3 * ((i + j) % 4) / 3),
                        at=(now - timedelta(days=offset)).isoformat(),
                        display_name=entry["display_name"],
                        conn=conn,
                        autocommit=False,
                    )
                    payments += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    print(f"  demo statement: {len(spec['payees'])} payees, {payments:,} crowd payments")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--with-demo-payees", action="store_true")
    ap.add_argument("--demo-statement", action="store_true",
                    help="seed the counterparty crowd for docs/demo/DEMO_UPI_Statement.pdf")
    ap.add_argument("--db", help="operate on this database file instead of the default")
    args = ap.parse_args()

    if args.db:
        _ps.DB_PATH = Path(args.db)

    conn = connect()
    try:
        bootstrap(conn, args.reset)
        if args.with_demo_payees:
            demo_payees(conn)
        if args.demo_statement:
            demo_statement_payees(conn)
        print("\n  top payees by distinct payers:")
        for r in conn.execute(
            """SELECT p.vpa, COUNT(*) AS payers, r.payment_count
               FROM payee_payers p JOIN payee_reputation r ON r.vpa = p.vpa
               GROUP BY p.vpa ORDER BY payers DESC LIMIT 8"""
        ):
            print(f"    {r['vpa']:<34} payers={r['payers']:>4}  payments={r['payment_count']:>5}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
