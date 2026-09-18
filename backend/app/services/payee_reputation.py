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
from backend.app.services.graph_cache import observe_edge
from backend.app.services.vpa import (
    VpaFinding,
    graded,
    normalise_vpa,
    total_weight,
)


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
    # Graph structures live alongside the edges they are derived from, and are
    # written in the same transaction, so they cannot disagree with them.
    from backend.app.services.graph_cache import ensure_schema as _graph_schema

    _graph_schema(conn)
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
        return total_weight(self.findings)

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
            # Same transaction as the two upserts above. Committing an edge
            # and failing its graph structures would leave a payee whose
            # cached shape says it has fewer payers than the edge table holds,
            # and nothing downstream could detect the disagreement.
            observe_edge(conn, key, payer_id)
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


def payer_has_paid(vpa: str, payer_id: Optional[str],
                   conn: Optional[sqlite3.Connection] = None) -> Optional[bool]:
    """Has THIS payer paid THIS payee before?

    This is the question the model's `payee_is_new` feature was trained on, and
    until now nothing answered it: serving substituted "does this payee have
    any repeat payers at all", which is a property of the payee's whole
    network and is true for almost every payee. The two are different
    questions, and the substitution cost most of the model's recall.

    Returns None when there is no payer to ask about, so the caller can tell
    "not known before" apart from "we cannot say".
    """
    if not payer_id:
        return None
    key = normalise_vpa(vpa)
    own = conn is None
    conn = conn or connect()
    try:
        row = conn.execute(
            "SELECT payments FROM payee_payers WHERE vpa = ? AND payer_id = ?",
            (key, str(payer_id)),
        ).fetchone()
    finally:
        if own:
            conn.close()
    return bool(row and (row["payments"] or 0) > 0)


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
        # The single most common finding in the whole system: on a fresh
        # deployment EVERY payee is unseen, so this fired on every check at a
        # flat 12 and became a constant added to every score. Combined with any
        # one high-severity finding it produced 35 + 0.4*12 = 39.8 -> 40, which
        # is why almost every test came out at 40.
        #
        # It is also the weakest evidence here. "We have never seen this
        # address" says almost nothing on a network with little history - it is
        # the null result, not a red flag - so it is weighted at the bottom of
        # the warn band and left to be corroborated by something that actually
        # measures the payee.
        rep.findings.append(
            VpaFinding("payee_unseen", "warn",
                       "No payment history for this address. That is normal for a new "
                       "payee, and it is also what a freshly created account looks like.",
                       weight=6)
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
        # Three complaints and thirty are not the same thing.
        rep.findings.append(
            VpaFinding("payee_reported", "critical",
                       f"{rep.reports} different people have reported this address.",
                       weight=graded(3, 15, rep.reports, 72, 100))
        )
    elif rep.reports > 0:
        rep.findings.append(
            VpaFinding("payee_reported", "high",
                       f"{rep.reports} person(s) have reported this address.",
                       weight=graded(1, 2, rep.reports, 30, 46))
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
                       f"twice. That is how a collection account behaves.",
                       # Two measurements, averaged: how new the address is and
                       # how many strangers have already paid it. An account
                       # three days old with sixty one-shot payers is a far
                       # stronger case than one 29 days old with ten.
                       weight=(graded(30, 2, float(rep.age_days or 30), 60, 100)
                               + graded(10, 60, rep.distinct_payers, 60, 100)) / 2)
        )
    elif young and rep.distinct_payers >= 5:
        rep.findings.append(
            VpaFinding("new_and_busy", "high",
                       f"Only {rep.age_days} days old but already paid by "
                       f"{rep.distinct_payers} different people.",
                       weight=(graded(30, 2, float(rep.age_days or 30), 24, 52)
                               + graded(5, 40, rep.distinct_payers, 24, 52)) / 2)
        )
    elif one_shot and rep.distinct_payers >= 15:
        rep.findings.append(
            VpaFinding("no_repeat_payers", "warn",
                       f"{rep.distinct_payers} people have paid this address and almost "
                       f"none came back. Real businesses keep customers.",
                       weight=graded(15, 80, rep.distinct_payers, 10, 22))
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
                       f"(Rs {rep.mean_amount:,.0f}), across {rep.distinct_payers} payers.",
                       # A spread of 0.02 across 50 payers is a fixed "fee";
                       # 0.14 across 8 is a shop with a popular item.
                       weight=(graded(0.15, 0.0, rep.amount_spread, 24, 52)
                               + graded(8, 50, rep.distinct_payers, 24, 52)) / 2)
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
