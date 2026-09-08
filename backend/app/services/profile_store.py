from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "behavior_profiles.db"


def _get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS statement_transactions (
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
            created_at TEXT NOT NULL
        )
        """
    )
    # Older databases predate txn_type; add it rather than losing their rows.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(statement_transactions)")}
    if "txn_type" not in columns:
        conn.execute(
            "ALTER TABLE statement_transactions ADD COLUMN txn_type TEXT NOT NULL DEFAULT 'DEBIT'"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS behavior_profiles (
            user_id TEXT PRIMARY KEY,
            profile_json TEXT NOT NULL,
            transaction_count INTEGER NOT NULL,
            source_type TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    # H3: every profile read and every statement listing filtered on user_id
    # with no index, so each one scanned the whole table.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_stmt_user ON statement_transactions(user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_stmt_user_ts ON statement_transactions(user_id, timestamp)"
    )

    # C4: the natural key for a statement line. With this in place,
    # INSERT OR IGNORE makes re-uploading the same statement a no-op.
    # Skipped when the table still holds duplicates from before the fix -
    # scripts/rebuild_profiles.py cleans those up, and the index is created
    # on the next connection.
    try:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_stmt_tx
            ON statement_transactions(
                user_id, timestamp, amount, merchant, reference_number
            )
            """
        )
    except sqlite3.IntegrityError:
        pass

    conn.commit()
    return conn


def save_statement_transactions(
    user_id: str,
    statement_id: str,
    source_type: str,
    transactions: list[dict[str, Any]],
) -> int:
    created_at = datetime.utcnow().isoformat()
    conn = _get_connection()
    before = conn.execute("SELECT COUNT(*) FROM statement_transactions").fetchone()[0]

    with conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO statement_transactions (
                statement_id,
                user_id,
                timestamp,
                amount,
                merchant,
                upi_id,
                status,
                reference_number,
                source_type,
                raw_line,
                txn_type,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    statement_id,
                    user_id,
                    tx.get("timestamp"),
                    float(tx.get("amount", 0)),
                    tx.get("merchant"),
                    tx.get("upi_id"),
                    tx.get("status"),
                    tx.get("reference_number"),
                    source_type,
                    tx.get("raw_line"),
                    str(tx.get("txn_type") or "DEBIT").upper(),
                    created_at,
                )
                for tx in transactions
            ],
        )

    after = conn.execute("SELECT COUNT(*) FROM statement_transactions").fetchone()[0]
    conn.close()
    # Rows already present are skipped, so report what was actually stored.
    return after - before


def get_user_transactions(user_id: str) -> pd.DataFrame:
    conn = _get_connection()
    query = """
        SELECT
            statement_id,
            user_id,
            timestamp,
            amount,
            merchant,
            upi_id,
            status,
            reference_number,
            source_type,
            raw_line,
            txn_type,
            created_at
        FROM statement_transactions
        WHERE user_id = ?
        ORDER BY COALESCE(timestamp, created_at)
    """
    df = pd.read_sql_query(query, conn, params=[user_id])
    conn.close()
    return df


def save_behavior_profile(
    user_id: str,
    source_type: str,
    profile: dict[str, Any],
    transaction_count: int,
) -> None:
    conn = _get_connection()
    updated_at = datetime.utcnow().isoformat()

    with conn:
        conn.execute(
            """
            INSERT INTO behavior_profiles (
                user_id,
                profile_json,
                transaction_count,
                source_type,
                updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                profile_json = excluded.profile_json,
                transaction_count = excluded.transaction_count,
                source_type = excluded.source_type,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                json.dumps(profile),
                transaction_count,
                source_type,
                updated_at,
            ),
        )

    conn.close()


def get_behavior_profile(user_id: str) -> dict[str, Any] | None:
    conn = _get_connection()
    row = conn.execute(
        """
        SELECT user_id, profile_json, transaction_count, source_type, updated_at
        FROM behavior_profiles
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    profile = json.loads(row["profile_json"])
    profile["user_id"] = row["user_id"]
    profile["transaction_count"] = row["transaction_count"]
    profile["source_type"] = row["source_type"]
    profile["updated_at"] = row["updated_at"]
    return profile

def get_all_edges() -> list[dict[str, str]]:
    conn = _get_connection()
    edges = []
    try:
        with conn:
            cursor = conn.execute(
                "SELECT DISTINCT user_id, merchant FROM statement_transactions WHERE merchant IS NOT NULL AND merchant != 'UNKNOWN_MERCHANT' LIMIT 1000"
            )
            rows = cursor.fetchall()
            for row in rows:
                edges.append({
                    "user": row["user_id"],
                    "merchant": row["merchant"]
                })
        return edges
    except Exception:
        return []

def create_user(user_id: str, username: str, password_hash: str) -> bool:
    conn = _get_connection()
    created_at = datetime.utcnow().isoformat()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO users (id, username, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, username, password_hash, created_at),
            )
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_user_by_username(username: str) -> dict[str, Any] | None:
    conn = _get_connection()
    row = conn.execute(
        "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
        (username,)
    ).fetchone()
    conn.close()

    if row is None:
        return None
    return dict(row)
