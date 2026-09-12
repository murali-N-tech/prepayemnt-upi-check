"""Repair the statement store and rebuild every behaviour profile.

Profiles already in the database were computed from inputs that had four
bugs: the CSV time column was dropped, PDF dates had month and day swapped,
PDF times defaulted to noon, credits were counted as spending, and page
headers were stored as transactions. Fixing the parsers does not fix rows
already written, so this script repairs the data.

Run the stages in order (each is idempotent, so re-running is safe):

    python scripts/rebuild_profiles.py report
    python scripts/rebuild_profiles.py truncate --max-rows 20000
    python scripts/rebuild_profiles.py dedupe
    python scripts/rebuild_profiles.py junk
    python scripts/rebuild_profiles.py reparse
    python scripts/rebuild_profiles.py profiles
    python scripts/rebuild_profiles.py vacuum

Or `all` to run every stage in sequence.

NOTE: `reparse` can only repair users whose original statement was kept in
data/uploaded_statements (the "retain original file" checkbox). For every
other user the stored timestamps keep whatever the old parser produced;
re-uploading their statement is the only way to correct those.
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
    parse_statement_file,
)

# COALESCE so NULLs compare equal. GROUP BY already treats them that way,
# but the UNIQUE index built from this key did not, and that is what makes
# INSERT OR IGNORE work on re-upload. See profile_store._ensure_schema.
NATURAL_KEY = (
    "user_id, COALESCE(timestamp, ''), amount, COALESCE(merchant, ''), "
    "COALESCE(reference_number, '')"
)
UPLOADS = ROOT / "data" / "uploaded_statements"

COLUMNS = (
    "statement_id, user_id, timestamp, amount, merchant, upi_id, status, "
    "reference_number, source_type, raw_line, txn_type, time_known, created_at"
)


def _open(path: Path) -> sqlite3.Connection:
    """Open a database, applying the schema migrations first.

    Opening a --db copy with a plain sqlite3.connect skipped _ensure_schema,
    so a column added since that copy was taken was simply missing and the
    stage failed. Route everything through the same setup the app uses.
    """
    import backend.app.services.profile_store as store

    store.DB_PATH = path
    store.DATA_DIR = path.parent
    store._SCHEMA_DONE.discard(str(path.resolve()))
    return store._get_connection()


def stage_compact(conn: sqlite3.Connection, max_rows: int) -> None:
    """Rebuild the table keeping, per user, the newest max_rows rows that have a
    positive amount and are not exact duplicates.

    Rebuilding is far cheaper than deleting: it writes ~23k rows instead of
    deleting ~230k.
    """
    conn.execute("DROP TABLE IF EXISTS st_new")
    conn.execute(
        """
        CREATE TABLE st_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            statement_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            timestamp TEXT,
            amount REAL NOT NULL,
            merchant TEXT,
            upi_id TEXT,
            status TEXT,
            reference_number TEXT,
            source_type TEXT,
            raw_line TEXT,
            txn_type TEXT NOT NULL DEFAULT 'DEBIT',
            -- Was missing here. The rebuild dropped the column, _ensure_schema
            -- re-added it on the next open with DEFAULT 1, and every row
            -- fixtimes had marked "no time recorded" silently became a real
            -- midnight or noon payment again.
            time_known INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    with conn:
        conn.execute(
            f"""
            INSERT INTO st_new ({COLUMNS})
            SELECT statement_id, user_id, timestamp, amount, merchant, upi_id, status,
                   reference_number, source_type, raw_line,
                   UPPER(COALESCE(NULLIF(TRIM(txn_type), ''), 'DEBIT')),
                   COALESCE(time_known, 1), created_at
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY COALESCE(timestamp, created_at) DESC, id DESC
                ) AS rn
                FROM statement_transactions
                WHERE amount > 0
                  AND id IN (
                      SELECT MIN(id) FROM statement_transactions GROUP BY {NATURAL_KEY}
                  )
            )
            WHERE rn <= ?
            """,
            (max_rows,),
        )
        conn.execute("DROP TABLE statement_transactions")
        conn.execute("ALTER TABLE st_new RENAME TO statement_transactions")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_stmt_user ON statement_transactions(user_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_stmt_user_ts ON statement_transactions(user_id, timestamp)"
        )
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS ux_stmt_tx_v2 ON statement_transactions({NATURAL_KEY})"
        )
    n = conn.execute("SELECT COUNT(*) FROM statement_transactions").fetchone()[0]
    print(f"  table rebuilt: {n:,} rows kept")


def mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def stage_report(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM statement_transactions").fetchone()[0]
    distinct = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT {NATURAL_KEY} FROM statement_transactions)"
    ).fetchone()[0]
    print(f"  rows {total:,}   distinct {distinct:,}   duplicates {total - distinct:,}")
    print(f"  database {mb(DB_PATH.stat().st_size if DB_PATH.exists() else 0)}")
    for uid, n in conn.execute(
        "SELECT user_id, COUNT(*) FROM statement_transactions GROUP BY user_id ORDER BY 2 DESC"
    ):
        noon = conn.execute(
            "SELECT COUNT(*) FROM statement_transactions "
            "WHERE user_id = ? AND substr(timestamp, 12, 5) = '12:00'",
            (uid,),
        ).fetchone()[0]
        flag = f"  ({noon:,} stuck at 12:00)" if noon else ""
        print(f"    {uid:<26} {n:>8,}{flag}")


def stage_truncate(conn: sqlite3.Connection, max_rows: int) -> None:
    oversized = [
        (uid, n)
        for uid, n in conn.execute(
            "SELECT user_id, COUNT(*) FROM statement_transactions GROUP BY user_id"
        )
        if n > max_rows
    ]
    if not oversized:
        print("  nothing over the cap")
        return
    for uid, n in oversized:
        conn.execute("DROP TABLE IF EXISTS keep_ids")
        conn.execute(
            """CREATE TEMP TABLE keep_ids AS
               SELECT id FROM statement_transactions WHERE user_id = ?
               ORDER BY COALESCE(timestamp, created_at) DESC LIMIT ?""",
            (uid, max_rows),
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_keep ON keep_ids(id)")
        with conn:
            conn.execute(
                "DELETE FROM statement_transactions "
                "WHERE user_id = ? AND id NOT IN (SELECT id FROM keep_ids)",
                (uid,),
            )
        conn.execute("DROP TABLE IF EXISTS keep_ids")
        print(f"  {uid}: {n:,} -> {max_rows:,}")


def stage_dedupe(conn: sqlite3.Connection) -> None:
    with conn:
        cur = conn.execute(
            f"""DELETE FROM statement_transactions WHERE id NOT IN
                (SELECT MIN(id) FROM statement_transactions GROUP BY {NATURAL_KEY})"""
        )
    print(f"  removed {cur.rowcount:,} duplicate rows")
    try:
        with conn:
            conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ux_stmt_tx_v2 "
                f"ON statement_transactions({NATURAL_KEY})"
            )
        print("  unique index ux_stmt_tx_v2 in place")
    except sqlite3.IntegrityError as exc:
        print(f"  unique index not created: {exc}")


def stage_junk(conn: sqlite3.Connection) -> None:
    junk = [
        r["id"]
        for r in conn.execute("SELECT id, merchant, amount FROM statement_transactions")
        if (r["amount"] or 0) <= 0 or _looks_like_header(r["merchant"] or "")
    ]
    if junk:
        with conn:
            conn.executemany(
                "DELETE FROM statement_transactions WHERE id = ?", [(i,) for i in junk]
            )
    with conn:
        conn.execute(
            "UPDATE statement_transactions SET txn_type = 'DEBIT' "
            "WHERE txn_type IS NULL OR TRIM(txn_type) = ''"
        )
    print(f"  removed {len(junk):,} header / zero-amount rows")



# The exact clock values older parsers wrote when a statement carried no time:
# 00:00:00 from the CSV path, 12:00:00 from the PDF path.
PLACEHOLDER_CLOCKS = ("00:00:00", "12:00:00")

# A user's real payments never pile onto one exact second. Measured on this
# data the largest genuine share is 3%, while every placeholder sits between
# 33% and 100%, so anything at or above this is a parser artefact - and only
# the two values above are ever eligible, so a genuine noon payment inside a
# normal spread can never be marked.
PLACEHOLDER_SHARE = 0.15


def stage_fixtimes(conn: sqlite3.Connection) -> None:
    """Mark parser placeholders as "no time recorded".

    Stored, a placeholder is indistinguishable from a real payment at that
    hour, so a statement with no times at all produced a confident "most
    active hour" that was never in the data - 12:00, every time.
    """
    total_marked = 0
    for (uid,) in conn.execute("SELECT DISTINCT user_id FROM statement_transactions"):
        total = conn.execute(
            "SELECT COUNT(*) FROM statement_transactions WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        if not total:
            continue

        for clock in PLACEHOLDER_CLOCKS:
            n = conn.execute(
                "SELECT COUNT(*) FROM statement_transactions "
                "WHERE user_id = ? AND substr(timestamp, 12, 8) = ?",
                (uid, clock),
            ).fetchone()[0]
            share = n / total
            if n < 5 or share < PLACEHOLDER_SHARE:
                continue
            with conn:
                conn.execute(
                    "UPDATE statement_transactions SET time_known = 0 "
                    "WHERE user_id = ? AND substr(timestamp, 12, 8) = ?",
                    (uid, clock),
                )
            total_marked += n
            print(f"    {uid:24} {n:>6} of {total:>6} at {clock} ({share:.0%}) "
                  f"-> no time recorded")

    print(f"    {total_marked:,} rows marked" if total_marked
          else "    no placeholder clock times found")


def stage_reparse(conn: sqlite3.Connection) -> None:
    """Re-derive rows from retained source files, which is the only way to fix
    timestamps the old parser corrupted."""
    if not UPLOADS.exists():
        print("  no data/uploaded_statements directory")
        return

    by_user: dict[str, list[Path]] = {}
    for f in sorted(UPLOADS.iterdir()):
        if not f.is_file():
            continue
        uid = f.name.split("_stmt_")[0]
        by_user.setdefault(uid, []).append(f)

    known = {r[0] for r in conn.execute("SELECT DISTINCT user_id FROM statement_transactions")}
    for uid, files in by_user.items():
        if uid not in known:
            print(f"  {uid}: retained file but no rows, skipping")
            continue
        fresh: list[dict] = []
        for f in files:
            try:
                parsed = parse_statement_file(f.name, f.read_bytes())
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"  {uid}: {f.name} failed to re-parse ({exc})")
                continue
            fresh.extend(parsed["transactions"])
        if not fresh:
            print(f"  {uid}: re-parse produced nothing, leaving rows alone")
            continue
        with conn:
            conn.execute("DELETE FROM statement_transactions WHERE user_id = ?", (uid,))
            conn.executemany(
                """INSERT OR IGNORE INTO statement_transactions
                   (statement_id, user_id, timestamp, amount, merchant, upi_id, status,
                    reference_number, source_type, raw_line, txn_type, time_known,
                    created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                [
                    (
                        "stmt_rebuilt",
                        uid,
                        t.get("timestamp"),
                        float(t.get("amount") or 0),
                        t.get("merchant"),
                        t.get("upi_id"),
                        t.get("status"),
                        t.get("reference_number"),
                        "rebuilt",
                        t.get("raw_line"),
                        str(t.get("txn_type") or "DEBIT").upper(),
                        1 if t.get("time_known", True) else 0,
                    )
                    for t in fresh
                ],
            )
        n = conn.execute(
            "SELECT COUNT(*) FROM statement_transactions WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        print(f"  {uid}: re-parsed {len(files)} file(s) -> {n:,} rows")


def stage_profiles(conn: sqlite3.Connection) -> None:
    for (uid,) in conn.execute("SELECT DISTINCT user_id FROM statement_transactions"):
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
                """INSERT INTO behavior_profiles
                       (user_id, profile_json, transaction_count, source_type, updated_at)
                   VALUES (?, ?, ?,
                       COALESCE((SELECT source_type FROM behavior_profiles WHERE user_id = ?), 'mixed'),
                       datetime('now'))
                   ON CONFLICT(user_id) DO UPDATE SET
                       profile_json = excluded.profile_json,
                       transaction_count = excluded.transaction_count,
                       updated_at = excluded.updated_at""",
                (uid, json.dumps(profile), len(rows), uid),
            )
        print(
            f"    {uid:<26} n={len(rows):>6,}  avg={profile['avg_amount']:>9,.2f}  "
            f"max={profile['max_amount']:>10,.2f}  night={profile['night_transactions']:>4}  "
            f"hour={profile['most_active_hour']}  hours={len(profile['hourly_distribution'])}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "stage",
        choices=["report", "compact", "truncate", "dedupe", "junk", "fixtimes",
                 "reparse", "profiles", "vacuum", "all"],
    )
    ap.add_argument("--max-rows", type=int, default=20_000)
    ap.add_argument("--db", help="operate on this database file instead of the default")
    args = ap.parse_args()

    global DB_PATH
    if args.db:
        DB_PATH = Path(args.db)

    if args.stage == "vacuum":
        v = sqlite3.connect(DB_PATH)
        v.execute("VACUUM")
        v.close()
        print(f"  vacuumed -> {mb(DB_PATH.stat().st_size)}")
        return 0

    conn = _open(DB_PATH)
    stages = (
        # reparse before fixtimes: reparse replaces a user's rows wholesale,
        # so running fixtimes first marked rows that were about to be deleted.
        ["compact", "junk", "reparse", "fixtimes", "profiles"]
        if args.stage == "all"
        else [args.stage]
    )
    for name in stages:
        print(f"\n[{name}]")
        if name == "report":
            stage_report(conn)
        elif name == "compact":
            stage_compact(conn, args.max_rows)
        elif name == "truncate":
            stage_truncate(conn, args.max_rows)
        elif name == "dedupe":
            stage_dedupe(conn)
        elif name == "junk":
            stage_junk(conn)
        elif name == "fixtimes":
            stage_fixtimes(conn)
        elif name == "reparse":
            stage_reparse(conn)
        elif name == "profiles":
            stage_profiles(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
