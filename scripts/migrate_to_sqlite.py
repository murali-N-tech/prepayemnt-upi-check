"""Move the remaining file-based stores into SQLite.

Until now the project kept the same kinds of data in two places: Express wrote
users, statements and profiles to JSON files, Python wrote them to SQLite, and
scored transactions went to a CSV that was rewritten in full on every request.
That is the root of several findings at once - a profile built through one
backend was invisible to the other, and two writers on one CSV lose rows.

This folds everything into data/behavior_profiles.db. It is idempotent: the
unique index on statement lines means re-running inserts nothing, and users are
matched on username.

    python scripts/migrate_to_sqlite.py --dry-run
    python scripts/migrate_to_sqlite.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bcrypt  # noqa: E402

from backend.app.services.profile_store import _get_connection  # noqa: E402
from backend.app.services.transaction_store import _ensure as ensure_scored  # noqa: E402

DATA = ROOT / "data"
USERS_JSON = DATA / "users.json"
PROFILES_JSON = DATA / "behavior_profiles.json"
STATEMENTS_JSON = DATA / "statement_transactions.json"
TRANSACTIONS_CSV = ROOT / "transactions.csv"

# Accounts created while testing during the audit work. Not real users.
TEST_PREFIXES = (
    "e2e_", "payee_", "final_", "dbg_", "ok_", "g_", "m_", "csvprobe_",
    "probe2", "audit_probe", "dedupe_probe", "graph_", "model_",
)


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"  could not read {path.name}: {exc}")
        return None


def migrate_users(conn) -> None:
    users = _load(USERS_JSON) or []
    if not users:
        print("  users: nothing to migrate")
        return

    existing = {r[0] for r in conn.execute("SELECT username FROM users")}
    added = hashed = skipped = 0

    for u in users:
        username = (u.get("username") or "").strip()
        if not username or username in existing:
            continue
        if username.startswith(TEST_PREFIXES):
            skipped += 1
            continue

        pw_hash = u.get("password_hash")
        if not pw_hash and u.get("password"):
            # A plaintext record. Hash it here so the plaintext stops existing.
            pw_hash = bcrypt.hashpw(
                str(u["password"]).encode("utf-8"), bcrypt.gensalt(rounds=12)
            ).decode("utf-8")
            hashed += 1
        if not pw_hash:
            continue

        conn.execute(
                "INSERT OR IGNORE INTO users (id, username, password_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (u.get("user_id") or f"usr_{username}", username, pw_hash,
                 datetime.now(timezone.utc).isoformat()),
            )
        added += 1

    print(f"  users: +{added} migrated ({hashed} plaintext hashed on the way), "
          f"{skipped} test accounts dropped")


def migrate_statements(conn) -> None:
    rows = _load(STATEMENTS_JSON) or []
    if not rows:
        print("  statements: nothing to migrate")
        return
    before = conn.execute("SELECT COUNT(*) FROM statement_transactions").fetchone()[0]
    conn.executemany(
            """INSERT OR IGNORE INTO statement_transactions
               (statement_id, user_id, timestamp, amount, merchant, upi_id, status,
                reference_number, source_type, raw_line, txn_type, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    t.get("statement_id") or "stmt_migrated",
                    t.get("user_id"),
                    t.get("timestamp"),
                    float(t.get("amount") or 0),
                    t.get("merchant"),
                    t.get("upi_id"),
                    t.get("status"),
                    t.get("reference_number"),
                    t.get("source_type") or "migrated",
                    t.get("raw_line"),
                    str(t.get("txn_type") or "DEBIT").upper(),
                    t.get("created_at") or datetime.now(timezone.utc).isoformat(),
                )
                for t in rows
                if t.get("user_id") and float(t.get("amount") or 0) > 0
            ],
        )
    after = conn.execute("SELECT COUNT(*) FROM statement_transactions").fetchone()[0]
    print(f"  statements: {len(rows)} in JSON, +{after - before} new "
          f"({len(rows) - (after - before)} already present)")


def migrate_profiles(conn) -> None:
    """Profiles are recomputed from the statement rows rather than copied.

    A profile in the JSON store was produced by the pre-fix pipeline, so
    copying it would carry the corrupted values straight back in.
    """
    from backend.app.services.statement_parser import generate_behavior_profile

    users = [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM statement_transactions")]
    for uid in users:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM statement_transactions WHERE user_id = ?", (uid,))]
        if not rows:
            continue
        profile = generate_behavior_profile(rows)
        conn.execute(
            """INSERT INTO behavior_profiles
                   (user_id, profile_json, transaction_count, source_type, updated_at)
               VALUES (?, ?, ?, COALESCE(
                   (SELECT source_type FROM behavior_profiles WHERE user_id = ?), 'migrated'),
                   datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
                   profile_json = excluded.profile_json,
                   transaction_count = excluded.transaction_count,
                   updated_at = excluded.updated_at""",
            (uid, json.dumps(profile), len(rows), uid),
        )
    print(f"  profiles: recomputed for {len(users)} users from the migrated rows")


def migrate_scored(conn) -> None:
    if not TRANSACTIONS_CSV.exists():
        print("  scored transactions: no CSV")
        return
    with TRANSACTIONS_CSV.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    before = conn.execute("SELECT COUNT(*) FROM scored_transactions").fetchone()[0]

    def num(v, default=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    conn.executemany(
            """INSERT OR IGNORE INTO scored_transactions
               (transaction_id, amount, device_score, location_score, velocity_score,
                sender, receiver, timestamp, risk, risk_score)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    r.get("transaction_id"), num(r.get("amount")),
                    num(r.get("device_score")), num(r.get("location_score")),
                    num(r.get("velocity_score")), r.get("sender"), r.get("receiver"),
                    r.get("timestamp"), int(num(r.get("risk"))), int(num(r.get("risk_score"))),
                )
                for r in rows if r.get("transaction_id")
            ],
        )
    after = conn.execute("SELECT COUNT(*) FROM scored_transactions").fetchone()[0]
    print(f"  scored transactions: {len(rows)} in CSV, +{after - before} new")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = _get_connection()
    ensure_scored(conn)
    print("migrating file stores into data/behavior_profiles.db")
    try:
        conn.execute("BEGIN")
        migrate_users(conn)
        migrate_statements(conn)
        migrate_scored(conn)
        migrate_profiles(conn)
        # The dry run does the work and throws it away, so the numbers it
        # prints are the numbers that would actually apply.
        conn.rollback() if args.dry_run else conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if args.dry_run:
        print("\n(dry run - nothing changed)")
    else:
        print("\nThe JSON files and transactions.csv are now redundant. They are kept\n"
              "on disk until you have confirmed the app works, then can be deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
