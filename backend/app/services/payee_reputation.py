"""Payee reputation: what everyone's history says about the address you are
about to pay.

This is the part a single wallet app cannot do and a shared risk service can.
A mule account has a shape - opened days ago, money arriving from many
unrelated payers who each pay once, amounts clustered in a narrow band - and
that shape is only visible when payers are pooled.

Aggregates only: counts, sums and a distinct-payer set. No payer can read
another payer's transactions out of this table.
"""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from backend.app.services.profile_store import _get_connection
from backend.app.services.vpa import SEVERITY_WEIGHT, VpaFinding, normalise_vpa


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payee_reputation (
            vpa             TEXT PRIMARY KEY,
            display_name    TEXT,
            first_seen      TEXT NOT NULL,
            last_seen       TEXT NOT NULL,
            payment_count   INTEGER NOT NULL DEFAULT 0,
            total_amount    REAL    NOT NULL DEFAULT 0,
            sum_sq_amount   REAL    NOT NULL DEFAULT 0,
            min_amount      REAL,
            max_amount      REAL,
            reports         INTEGER NOT NULL DEFAULT 0,
            blocked         INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    # One row per (payee, payer). Counting rows here is the distinct-payer
    # count, which is the signal a per-app view cannot produce.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payee_payers (
            vpa       TEXT NOT NULL,
            payer_id  TEXT NOT NULL,
            payments  INTEGER NOT NULL DEFAULT 1,
            first_at  TEXT NOT NULL,
            last_at   TEXT NOT NULL,
            PRIMARY KEY (vpa, payer_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payee_reports (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            vpa        TEXT NOT NULL,
            reporter   TEXT NOT NULL,
            reason     TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_payers_vpa ON payee_payers(vpa)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_reports_vpa ON payee_reports(vpa)")
    conn.commit()


def payee_key(vpa: Optional[str] = None, name: Optional[str] = None) -> str:
    """Identity used to look a payee up.

    A real VPA when we have one. Otherwise the merchant name under a `name:`
    prefix, so a name-keyed payee can never be confused with an address.
    """
    key = normalise_vpa(vpa or "")
    if key and "@" in key:
        return key
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return f"name:{slug}" if slug else ""


def connect() -> sqlite3.Connection:
    conn = _get_connection()
    _ensure_schema(conn)
    return conn


@dataclass
class PayeeReputation:
    vpa: str
    known: bool = False
    display_name: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    age_days: Optional[int] = None
    payment_count: int = 0
    distinct_payers: int = 0
    repeat_payers: int = 0
    total_amount: float = 0.0
    mean_amount: Optional[float] = None
    amount_spread: Optional[float] = None   # coefficient of variation
    reports: int = 0
    blocked: bool = False
    findings: list[VpaFinding] = field(default_factory=list)

    @property
    def score(self) -> int:
        return min(100, sum(SEVERITY_WEIGHT[f.severity] for f in self.findings))

    def as_dict(self) -> dict[str, Any]:
        return {
            "vpa": self.vpa,
            "known": self.known,
            "display_name": self.display_name,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "age_days": self.age_days,
            "payment_count": self.payment_count,
            "distinct_payers": self.distinct_payers,
            "repeat_payers": self.repeat_payers,
            "total_amount": round(self.total_amount, 2),
            "mean_amount": round(self.mean_amount, 2) if self.mean_amount is not None else None,
            "amount_spread": round(self.amount_spread, 3) if self.amount_spread is not None else None,
            "reports": self.reports,
            "blocked": self.blocked,
        }


def record_payment(
    vpa: str,
    payer_id: str,
    amount: float,
    at: Optional[str] = None,
    display_name: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    autocommit: bool = True,
) -> None:
    """Fold one payment into the payee's aggregates.

    Pass autocommit=False when loading in bulk and committing once; a commit
    per payment is thousands of fsyncs.
    """
    key = normalise_vpa(vpa)
    if not key:
        return
    when = at or _utcnow()
    amount = float(amount or 0)

    own = conn is None
    conn = conn or connect()
    try:
        if autocommit:
            conn.execute("BEGIN")
        try:
            conn.execute(
                """
                INSERT INTO payee_reputation
                    (vpa, display_name, first_seen, last_seen, payment_count,
                     total_amount, sum_sq_amount, min_amount, max_amount)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(vpa) DO UPDATE SET
                    display_name  = COALESCE(payee_reputation.display_name, excluded.display_name),
                    first_seen    = MIN(payee_reputation.first_seen, excluded.first_seen),
                    last_seen     = MAX(payee_reputation.last_seen, excluded.last_seen),
                    payment_count = payee_reputation.payment_count + 1,
                    total_amount  = payee_reputation.total_amount + excluded.total_amount,
                    sum_sq_amount = payee_reputation.sum_sq_amount + excluded.sum_sq_amount,
                    min_amount    = MIN(COALESCE(payee_reputation.min_amount, excluded.min_amount), excluded.min_amount),
                    max_amount    = MAX(COALESCE(payee_reputation.max_amount, excluded.max_amount), excluded.max_amount)
                """,
                (key, display_name, when, when, amount, amount * amount, amount, amount),
            )
            conn.execute(
                """
                INSERT INTO payee_payers (vpa, payer_id, payments, first_at, last_at)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(vpa, payer_id) DO UPDATE SET
                    payments = payee_payers.payments + 1,
                    first_at = MIN(payee_payers.first_at, excluded.first_at),
                    last_at  = MAX(payee_payers.last_at,  excluded.last_at)
                """,
                (key, payer_id, when, when),
            )
        except Exception:
            if autocommit:
                conn.rollback()
            raise
        else:
            if autocommit:
                conn.commit()
    finally:
        if own:
            conn.close()


def report_payee(vpa: str, reporter: str, reason: str = "") -> int:
    """Record that a person reported this payee. Returns the new report count."""
    key = normalise_vpa(vpa)
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO payee_reports (vpa, reporter, reason, created_at) VALUES (?,?,?,?)",
                (key, reporter, reason[:500], _utcnow()),
            )
            # One report per person counts once.
            distinct = conn.execute(
                "SELECT COUNT(DISTINCT reporter) FROM payee_reports WHERE vpa = ?", (key,)
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO payee_reputation (vpa, first_seen, last_seen, reports)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(vpa) DO UPDATE SET reports = excluded.reports
                """,
                (key, _utcnow(), _utcnow(), distinct),
            )
        return distinct
    finally:
        conn.close()


def set_blocked(vpa: str, blocked: bool = True) -> None:
    key = normalise_vpa(vpa)
    conn = connect()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO payee_reputation (vpa, first_seen, last_seen, blocked)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(vpa) DO UPDATE SET blocked = excluded.blocked
                """,
                (key, _utcnow(), _utcnow(), 1 if blocked else 0),
            )
    finally:
        conn.close()


def _days_since(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - ts).days)


def assess_payee(vpa: str, conn: Optional[sqlite3.Connection] = None) -> PayeeReputation:
    """Look the payee up and score the shape of their incoming payments."""
    key = normalise_vpa(vpa)
    rep = PayeeReputation(vpa=key)

    own = conn is None
    conn = conn or connect()
    try:
        row = conn.execute("SELECT * FROM payee_reputation WHERE vpa = ?", (key,)).fetchone()
        payers = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(payments > 1), 0) AS repeat_n "
            "FROM payee_payers WHERE vpa = ?",
            (key,),
        ).fetchone()
    finally:
        if own:
            conn.close()

    rep.distinct_payers = payers["n"] or 0
    rep.repeat_payers = payers["repeat_n"] or 0

    if row is None and rep.distinct_payers == 0:
        rep.findings.append(
            VpaFinding("payee_unseen", "warn",
                       "No payment history for this address. That is normal for a new "
                       "payee, and it is also what a freshly created account looks like.")
        )
        return rep

    rep.known = True
    if row is not None:
        rep.display_name = row["display_name"]
        rep.first_seen = row["first_seen"]
        rep.last_seen = row["last_seen"]
        rep.payment_count = row["payment_count"] or 0
        rep.total_amount = row["total_amount"] or 0.0
        rep.reports = row["reports"] or 0
        rep.blocked = bool(row["blocked"])
        rep.age_days = _days_since(row["first_seen"])

        if rep.payment_count > 0:
            rep.mean_amount = rep.total_amount / rep.payment_count
            variance = max(
                0.0,
                (row["sum_sq_amount"] or 0.0) / rep.payment_count - rep.mean_amount ** 2,
            )
            if rep.mean_amount > 0:
                rep.amount_spread = math.sqrt(variance) / rep.mean_amount

    # ── Signals ───────────────────────────────────────────────────────────
    if rep.blocked:
        rep.findings.append(
            VpaFinding("payee_blocked", "critical",
                       "This address is on the block list. Do not pay it.")
        )

    if rep.reports >= 3:
        rep.findings.append(
            VpaFinding("payee_reported", "critical",
                       f"{rep.reports} different people have reported this address.")
        )
    elif rep.reports > 0:
        rep.findings.append(
            VpaFinding("payee_reported", "high",
                       f"{rep.reports} person(s) have reported this address.")
        )

    young = rep.age_days is not None and rep.age_days <= 30
    one_shot = (
        rep.distinct_payers >= 5
        and rep.repeat_payers / max(rep.distinct_payers, 1) < 0.2
    )

    # The collection-account pattern: new, many unrelated payers, nobody returns.
    if young and rep.distinct_payers >= 10 and one_shot:
        rep.findings.append(
            VpaFinding("mule_pattern", "critical",
                       f"Opened {rep.age_days} days ago and already taking payments from "
                       f"{rep.distinct_payers} different people, almost none of whom paid "
                       f"twice. That is how a collection account behaves.")
        )
    elif young and rep.distinct_payers >= 5:
        rep.findings.append(
            VpaFinding("new_and_busy", "high",
                       f"Only {rep.age_days} days old but already paid by "
                       f"{rep.distinct_payers} different people.")
        )
    elif one_shot and rep.distinct_payers >= 15:
        rep.findings.append(
            VpaFinding("no_repeat_payers", "warn",
                       f"{rep.distinct_payers} people have paid this address and almost "
                       f"none came back. Real businesses keep customers.")
        )

    # Amounts clustered in a narrow band across many payers is what a fixed
    # "fee" or "fine" scam looks like.
    if (
        rep.amount_spread is not None
        and rep.amount_spread < 0.15
        and rep.distinct_payers >= 8
        and rep.payment_count >= 10
    ):
        rep.findings.append(
            VpaFinding("uniform_amounts", "high",
                       f"Nearly every payment here is about the same amount "
                       f"(Rs {rep.mean_amount:,.0f}), across {rep.distinct_payers} payers.")
        )

    # Reassurance, worth as much as a warning.
    established = (
        rep.age_days is not None
        and rep.age_days >= 90
        and rep.payment_count >= 20
        and rep.repeat_payers >= 3
        and rep.reports == 0
    )
    if established:
        rep.findings.append(
            VpaFinding("payee_established", "info",
                       f"Paid {rep.payment_count} times over {rep.age_days} days, with "
                       f"{rep.repeat_payers} people returning. No reports.")
        )

    return rep
