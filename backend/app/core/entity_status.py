"""How much the system knows about a party to a payment, and nothing more.

Four statuses, and the distinctions between them matter more than the
statuses themselves:

    REGISTERED  someone holds an account here under this address
    VERIFIED    a trusted verification step has tied the address to an identity
    OBSERVED    the address appears in transaction data users have contributed,
                but nobody has claimed it
    UNKNOWN     no historical information exists

The rule this module exists to enforce is that none of these is a verdict.

    REGISTERED   is not SAFE       - anyone can create an account
    VERIFIED     is not FRAUD-FREE - a verified merchant can still be a front
    UNKNOWN      is not FRAUD      - most first payments are to strangers
    UNKNOWN      is not SAFE       - it means we cannot say, which is different

So nothing here returns a score, and nothing here is allowed to. Status
describes the *evidence available* about an entity; the risk engine decides
what that evidence is worth. Keeping the two apart is what stops the system
sliding into "registered users are trusted", which is how an identity layer
becomes an attack surface: the cheapest thing a fraudster can do is register.

The one thing status DOES legitimately control is which evidence families can
run at all, and that is expressed as an EvidenceLevel rather than as a number.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class EntityStatus(str, Enum):
    REGISTERED = "REGISTERED"
    VERIFIED = "VERIFIED"
    OBSERVED = "OBSERVED"
    UNKNOWN = "UNKNOWN"

    @property
    def has_history(self) -> bool:
        """Is there behavioural history to read?

        REGISTERED and VERIFIED say something about identity, not about
        behaviour: an account created this morning has an identity and no
        history at all. Only OBSERVED guarantees transaction data exists, and
        a registered address is usually observed as well - which is why this
        is a question about the reputation row, not about the status.
        """
        return self is EntityStatus.OBSERVED


class RelationshipStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"     # this payer has paid this payee before
    NEW = "NEW"                     # first payment, and we would know if not
    UNKNOWN = "UNKNOWN"             # we cannot tell - no payer identity, say


class EvidenceLevel(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    MINIMAL = "MINIMAL"


# How many distinct payers an address needs before its aggregate shape means
# anything. Below this the repeat-payer ratio and the arrival burst are
# computed from so few observations that they are noise, and reporting them as
# evidence would be claiming a precision the data does not support. Two payers
# with one payment each give a repeat ratio of exactly 0.0, which looks like a
# collection account and is actually just an empty sample.
MIN_PAYERS_FOR_SHAPE = 5


@dataclass(frozen=True)
class PayeeIdentity:
    """Everything known about a payee's standing, with no risk attached."""

    key: str
    status: EntityStatus
    history_available: bool          # is there enough data to read shape from?
    observed_payers: Optional[int] = None
    observed_payments: Optional[int] = None
    first_observed_at: Optional[str] = None
    verified_by: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.key,
            "status": self.status.value,
            "history_available": self.history_available,
            "observed_payers": self.observed_payers,
            "observed_payments": self.observed_payments,
            "first_observed_at": self.first_observed_at,
            "verified_by": self.verified_by,
        }


ENTITY_VERIFICATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS entity_verification (
    payee_key   TEXT PRIMARY KEY,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    method      TEXT,
    note        TEXT
)
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(ENTITY_VERIFICATION_SCHEMA)


def resolve_payee(key: str, conn: sqlite3.Connection) -> PayeeIdentity:
    """Decide a payee's status from what the database actually holds.

    Order matters, and it is verification first, then registration, then
    observation. A verified address that is also registered is reported as
    VERIFIED because that is the stronger claim about identity. Note that it
    is not the stronger claim about risk, and this function does not make one.
    """
    ensure_schema(conn)

    row = conn.execute(
        "SELECT verified_by FROM entity_verification WHERE payee_key = ?", (key,)
    ).fetchone()
    verified_by = row[0] if row else None

    reputation = conn.execute(
        """SELECT payment_count, first_seen FROM payee_reputation WHERE vpa = ?""",
        (key,),
    ).fetchone()
    payers = conn.execute(
        "SELECT COUNT(*) FROM payee_payers WHERE vpa = ?", (key,)
    ).fetchone()[0]

    registered = conn.execute(
        "SELECT 1 FROM users WHERE LOWER(COALESCE(upi_id, '')) = ? LIMIT 1", (key.lower(),)
    ).fetchone() is not None

    payments = reputation[0] if reputation else 0
    first_seen = reputation[1] if reputation else None

    # Enough distinct payers for the shape features to carry meaning. This is
    # deliberately NOT "does a reputation row exist": a row with one payer is
    # a row, and it supports no conclusion about repeat behaviour.
    history = payers >= MIN_PAYERS_FOR_SHAPE

    if verified_by:
        status = EntityStatus.VERIFIED
    elif registered:
        status = EntityStatus.REGISTERED
    elif payments > 0:
        status = EntityStatus.OBSERVED
    else:
        status = EntityStatus.UNKNOWN

    return PayeeIdentity(
        key=key,
        status=status,
        history_available=history,
        observed_payers=payers if payments > 0 else None,
        observed_payments=payments if payments > 0 else None,
        first_observed_at=first_seen,
        verified_by=verified_by,
    )


def resolve_relationship(
    key: str, payer_id: Optional[str], conn: sqlite3.Connection
) -> tuple[RelationshipStatus, Optional[dict[str, Any]]]:
    """This payer's own history with this payee.

    Returns UNKNOWN rather than NEW when there is no authenticated payer. The
    difference is the whole point: NEW asserts that we looked and found no
    prior payment, UNKNOWN admits we could not look. Collapsing the two would
    let an unauthenticated request masquerade as a verified first payment.
    """
    if not payer_id:
        return RelationshipStatus.UNKNOWN, None

    row = conn.execute(
        """SELECT payments, first_at, last_at FROM payee_payers
           WHERE vpa = ? AND payer_id = ?""",
        (key, payer_id),
    ).fetchone()

    if row is None or not row[0]:
        return RelationshipStatus.NEW, {
            "transaction_count": 0,
            "first_seen_at": None,
            "last_seen_at": None,
        }

    return RelationshipStatus.ESTABLISHED, {
        "transaction_count": int(row[0]),
        "first_seen_at": row[1],
        "last_seen_at": row[2],
    }


def record_verification(key: str, verified_by: str, method: str,
                        conn: sqlite3.Connection, note: str = "") -> None:
    from datetime import datetime, timezone

    ensure_schema(conn)
    conn.execute(
        """INSERT INTO entity_verification (payee_key, verified_by, verified_at, method, note)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(payee_key) DO UPDATE SET
               verified_by = excluded.verified_by,
               verified_at = excluded.verified_at,
               method      = excluded.method,
               note        = excluded.note""",
        (key, verified_by, datetime.now(timezone.utc).isoformat(), method, note),
    )
