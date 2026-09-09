"""Scored transactions.

This used to be a CSV that was read in full, concatenated with one new row and
written back on every prediction:

    df = pd.read_csv(DB_FILE); df = pd.concat([df, new]); df.to_csv(DB_FILE)

That is O(n^2) across a session, and with no locking two concurrent requests
read the same file and one silently overwrites the other's row. It also meant
a second process appending to the same file could lose rows outright.

Same SQLite database as everything else, with an index on the columns that are
actually queried.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

import pandas as pd

from backend.app.services.profile_store import _get_connection

COLUMNS = [
    "transaction_id", "amount", "device_score", "location_score",
    "velocity_score", "sender", "receiver", "timestamp", "risk", "risk_score",
]


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scored_transactions (
            transaction_id TEXT PRIMARY KEY,
            amount         REAL NOT NULL,
            device_score   REAL,
            location_score REAL,
            velocity_score REAL,
            sender         TEXT,
            receiver       TEXT,
            timestamp      TEXT,
            risk           INTEGER NOT NULL DEFAULT 0,
            risk_score     INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_scored_sender ON scored_transactions(sender)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_scored_ts ON scored_transactions(timestamp)")
    conn.commit()


def connect() -> sqlite3.Connection:
    conn = _get_connection()
    _ensure(conn)
    return conn


def save_transaction(tx: dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> None:
    """Append one scored transaction. A single INSERT, not a file rewrite."""
    own = conn is None
    conn = conn or connect()
    try:
        with conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO scored_transactions ({", ".join(COLUMNS)})
                    VALUES ({", ".join("?" * len(COLUMNS))})""",
                [tx.get(c) for c in COLUMNS],
            )
    finally:
        if own:
            conn.close()


def get_all_transactions(
    sender: Optional[str] = None,
    limit: int = 1000,
    conn: Optional[sqlite3.Connection] = None,
) -> pd.DataFrame:
    """Most recent transactions, newest last so tail() still means latest.

    Defaults to a bounded window: the previous version loaded every row on
    every call, which is what made the profile page unusable.
    """
    own = conn is None
    conn = conn or connect()
    try:
        # rowid is not exposed by a subquery, so it is aliased on the way out
        # and used to order the outer result deterministically.
        where = "WHERE sender = ?" if sender else ""
        params = ([sender] if sender else []) + [limit]
        df = pd.read_sql_query(
            f"""SELECT * FROM (
                    SELECT *, rowid AS _rid FROM scored_transactions {where}
                    ORDER BY created_at DESC, rowid DESC LIMIT ?
                ) ORDER BY created_at ASC, _rid ASC""",
            conn, params=params,
        )
        df = df.drop(columns=["_rid"], errors="ignore")
    finally:
        if own:
            conn.close()
    return df


def get_transaction(
    tx_id: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict[str, Any]]:
    own = conn is None
    conn = conn or connect()
    try:
        row = conn.execute(
            "SELECT * FROM scored_transactions WHERE transaction_id = ?", (tx_id,)
        ).fetchone()
    finally:
        if own:
            conn.close()
    return dict(row) if row else None
