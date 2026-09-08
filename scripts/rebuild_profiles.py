"""Repair the statement store and rebuild every behaviour profile.

The profiles in the database were computed from inputs that had three bugs
(dropped time column, credits counted as spending, page headers parsed as
transactions). Fixing the parser does not fix data already stored, so this
script cleans the rows and recomputes the profiles from them.

    python scripts/rebuild_profiles.py --dry-run     # report only
    python scripts/rebuild_profiles.py               # clean and rebuild

Nothing is deleted except exact duplicate rows and rows that are not
transactions (page headers, zero amounts). Pass --truncate-oversized to also
cap any single user at --max-rows transactions, newest first.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.services.profile_store import _get_connection, DB_PATH  # noqa: E402
from backend.app.services.statement_parser import (  # noqa: E402
    _looks_like_header,
    generate_behavior_profile,
)

NATURAL_KEY = "user_id, timestamp, amount, merchant, reference_number"


def human_bytes(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def report(conn: sqlite3.Connection, label: str) -> None:
    total = conn.execute("SELECT COUNT(*) FROM statement_transactions").fetchone()[0]
    distinct = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT {NATURAL_KEY} FROM statement_transactions)"
    ).fetchone()[0]
    size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    print(f"\n{label}")
    print(f"  rows            {total:,}")
    print(f"  distinct rows   {distinct:,}   (duplicates: {total - distinct:,})")
    print(f"  database size   {human_bytes(size)}")
    print("  per user:")
    for uid, n in conn.execute(
        "SELECT user_id, COUNT(*) FROM statement_transactions GROUP BY user_id ORDER BY 2 DESC"
    ):
        print(f"    {uid:<26} {n:>8,}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report without changing anything")
    ap.add_argument("--truncate-oversized", action="store_true",
                    help="cap each user at --max-rows transactions, newest kept")
    ap.add_argument("--max-rows", type=int, default=20_000)
    args = ap.parse_args()

    conn = _get_connection()
    report(conn, "BEFORE")

    # 1. exact duplicate statement lines
    dupes = conn.execute(
        f"""SELECT COUNT(*) FROM statement_transactions WHERE id NOT IN
            (SELECT MIN(id) FROM statement_transactions GROUP BY {NATURAL_KEY})"""
    ).fetchone()[0]

    # 2. rows that are not transactions
    junk_ids: list[int] = []
    for row in conn.execute(
        "SELECT id, merchant, amount, raw_line FROM statement_transactions"
    ):
        amount = row["amount"] or 0
        if amount <= 0 or _looks_like_header(row["merchant"] or ""):
            junk_ids.append(row["id"])

    print(f"\n  duplicate rows to remove   {dupes:,}")
    print(f"  header / zero-amount rows  {len(junk_ids):,}")

    oversized = [
        (uid, n)
        for uid, n in conn.execute(
            "SELECT user_id, COUNT(*) FROM statement_transactions GROUP BY user_id"
        )
        if n > args.max_rows
    ]
    if oversized:
        verb = "will be capped" if args.truncate_oversized else "NOT touched (pass --truncate-oversized)"
        print(f"  users over {args.max_rows:,} rows: "
              f"{', '.join(f'{u} ({n:,})' for u, n in oversized)} - {verb}")

    if args.dry_run:
        print("\n(dry run - nothing changed)")
        conn.close()
        return 0

    with conn:
        conn.execute(
            f"""DELETE FROM statement_transactions WHERE id NOT IN
                (SELECT MIN(id) FROM statement_transactions GROUP BY {NATURAL_KEY})"""
        )
        if junk_ids:
            conn.executemany(
                "DELETE FROM statement_transactions WHERE id = ?",
                [(i,) for i in junk_ids],
            )
        conn.execute(
            "UPDATE statement_transactions SET txn_type = 'DEBIT' "
            "WHERE txn_type IS NULL OR TRIM(txn_type) = ''"
        )
        if args.truncate_oversized:
            for uid, _ in oversized:
                conn.execute(
                    """DELETE FROM statement_transactions
                       WHERE user_id = ? AND id NOT IN (
                           SELECT id FROM statement_transactions
                           WHERE user_id = ?
                           ORDER BY COALESCE(timestamp, created_at) DESC
                           LIMIT ?
                       )""",
                    (uid, uid, args.max_rows),
                )

    # The unique index could not be created while duplicates existed.
    try:
        with conn:
            conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ux_stmt_tx ON statement_transactions({NATURAL_KEY})"
            )
        print("\n  unique index ux_stmt_tx created")
    except sqlite3.IntegrityError as exc:
        print(f"\n  could not create unique index: {exc}")

    # 3. recompute every profile from the cleaned rows
    print("\n  rebuilding profiles:")
    user_ids = [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM statement_transactions")]
    for uid in user_ids:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM statement_transactions WHERE user_id = ? "
                "ORDER BY COALESCE(timestamp, created_at)",
                (uid,),
            )
        ]
        profile = generate_behavior_profile(rows)
        with conn:
            conn.execute(
                """INSERT INTO behavior_profiles (user_id, profile_json, transaction_count, source_type, updated_at)
                   VALUES (?, ?, ?, COALESCE((SELECT source_type FROM behavior_profiles WHERE user_id = ?), 'mixed'),
                           datetime('now'))
                   ON CONFLICT(user_id) DO UPDATE SET
                       profile_json = excluded.profile_json,
                       transaction_count = excluded.transaction_count,
                       updated_at = excluded.updated_at""",
                (uid, json.dumps(profile), len(rows), uid),
            )
        print(f"    {uid:<26} n={len(rows):>7,}  avg={profile['avg_amount']:>10,.2f}  "
              f"max={profile['max_amount']:>11,.2f}  night={profile['night_transactions']:>5}  "
              f"hour={profile['most_active_hour']}")

    conn.close()

    # VACUUM must run outside a transaction and on its own connection.
    vac = sqlite3.connect(DB_PATH)
    vac.execute("VACUUM")
    vac.close()

    conn = _get_connection()
    report(conn, "AFTER")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
