"""Graph features the pre-payment path can read without rebuilding the graph.

The measurement that shaped this
--------------------------------
Before any of this existed, /payee/check issued three SQL statements and never
imported fraud_graph at all. It was not rebuilding anything - the graph family
was simply absent from the evidence, and a full rebuild (24.7 ms over 1,794
edges, and superlinear) lived behind GET /fraud-graph where a human waits for
a dashboard. So the risk was never a rebuild already on the payment path. It
was that the obvious way to make graph evidence available - call
graph_summary() from check_payee - would have put one there.

What is maintained, and when
----------------------------
Two structures, both written only during POST_PAYMENT_OBSERVATION, inside the
same transaction as the reputation upserts so they cannot disagree with it:

  payee_graph_cache   per-payee shape: how many payers, how many returned,
                      when the payers first arrived, how long the address has
                      been active. Recomputed for the ONE payee an observation
                      touched, from its own edges via the vpa index - bounded
                      by that payee's payer count, never by the graph.

  graph_components    a persisted union-find over payer and payee nodes. An
                      observation can only ADD an edge, and adding an edge can
                      only MERGE components, never split one. That is what
                      makes connected-component size incrementally maintainable
                      at all: union is near-constant time, whereas recomputing
                      components means walking every edge in the store.

The read path is then one indexed SELECT for shape and one bounded two-hop
query for payer overlap. Neither grows with the size of the graph.

What is NOT here
----------------
Ring detection. detect_rings() compares every eligible payee against every
other, and there is no incremental form of that - one new edge can create or
dissolve a ring anywhere. It stays on the dashboard path where the cost is
affordable, and the pre-payment path reports the overlap that underlies it
instead. Stated in graph_limitations() rather than left for someone to
discover.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from backend.app.services.vpa import normalise_vpa

# Thresholds mirror fraud_graph.signals_for so the two views of the same graph
# cannot quietly disagree about what counts as a finding.
MIN_FAN_IN = 10
ONE_SHOT_RATIO = 0.1
BURST_WINDOW_DAYS = 30
MIN_SHARED_PAYERS = 4
OVERLAP_RATIO = 0.6

# Both sides of an overlap need enough payers for "almost nobody comes back"
# to be a measurement rather than an artefact of being new. This is the same
# MIN_FAN_IN the shape findings already use, and it is applied here for the
# same reason: a payee three days old with five one-shot payers has not failed
# to retain customers, nobody has had time to return.
#
# It makes the pre-payment path STRICTER than fraud_graph.detect_rings, which
# needs only four payers a side. That divergence is deliberate. detect_rings
# feeds a dashboard list a human skims; a false positive costs a glance. This
# path stops a payment, and the audit found it blocking a household of five
# paying two new local shops - the exact false positive detect_rings names in
# its own docstring and does not actually prevent on cold start.
MIN_PAYERS_FOR_OVERLAP = MIN_FAN_IN

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS payee_graph_cache (
        vpa                TEXT PRIMARY KEY,
        payer_count        INTEGER NOT NULL DEFAULT 0,
        repeat_payer_count INTEGER NOT NULL DEFAULT 0,
        payments           INTEGER NOT NULL DEFAULT 0,
        arrival_first      TEXT,
        arrival_last       TEXT,
        activity_first     TEXT,
        activity_last      TEXT,
        updated_at         TEXT NOT NULL
    )
    """,
    # Union-find over the bipartite node set. `parent` points one step up the
    # tree; `size` is meaningful only on a root.
    """
    CREATE TABLE IF NOT EXISTS graph_components (
        node   TEXT PRIMARY KEY,
        parent TEXT NOT NULL,
        size   INTEGER NOT NULL DEFAULT 1
    )
    """,
    # The two-hop overlap query walks payer -> their other payees, so it needs
    # the payer side indexed. Without this it is a scan of every edge, which is
    # the rebuild by another name.
    "CREATE INDEX IF NOT EXISTS ix_payers_payer ON payee_payers(payer_id)",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA:
        conn.execute(statement)


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _days(a: Optional[str], b: Optional[str]) -> Optional[float]:
    start, end = _parse(a), _parse(b)
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds() / 86400.0)


# ── Union-find ───────────────────────────────────────────────────────────────

def _find(conn: sqlite3.Connection, node: str) -> Optional[str]:
    """Root of `node`, with path compression written back.

    Iterative rather than recursive: a long chain of payers and payees is
    exactly the shape that blows a recursion limit, and it is the shape a
    collection ring produces.
    """
    seen: list[str] = []
    current = node
    while True:
        row = conn.execute("SELECT parent FROM graph_components WHERE node = ?",
                           (current,)).fetchone()
        if row is None:
            return None
        parent = row[0]
        if parent == current:
            break
        seen.append(current)
        current = parent

    for stale in seen:
        if stale != current:
            conn.execute("UPDATE graph_components SET parent = ? WHERE node = ?",
                         (current, stale))
    return current


def _add_node(conn: sqlite3.Connection, node: str) -> str:
    conn.execute(
        "INSERT INTO graph_components (node, parent, size) VALUES (?, ?, 1) "
        "ON CONFLICT(node) DO NOTHING",
        (node, node),
    )
    return _find(conn, node) or node


def union(conn: sqlite3.Connection, a: str, b: str) -> None:
    """Merge the components of two nodes. Union by size, so trees stay shallow."""
    root_a, root_b = _add_node(conn, a), _add_node(conn, b)
    if root_a == root_b:
        return
    size_a = conn.execute("SELECT size FROM graph_components WHERE node = ?",
                          (root_a,)).fetchone()[0]
    size_b = conn.execute("SELECT size FROM graph_components WHERE node = ?",
                          (root_b,)).fetchone()[0]
    if size_a < size_b:
        root_a, root_b, size_a, size_b = root_b, root_a, size_b, size_a
    conn.execute("UPDATE graph_components SET parent = ? WHERE node = ?", (root_a, root_b))
    conn.execute("UPDATE graph_components SET size = ? WHERE node = ?", (size_a + size_b, root_a))


def component_size(conn: sqlite3.Connection, node: str) -> Optional[int]:
    """Read-only: _find compresses paths, so the read variant must not.

    Path compression is a write, and this is called from the pre-payment path.
    Walking without rewriting costs a few extra hops on a tree that union-by-
    size already keeps shallow.
    """
    current, hops = node, 0
    while hops < 64:
        row = conn.execute("SELECT parent, size FROM graph_components WHERE node = ?",
                           (current,)).fetchone()
        if row is None:
            return None
        if row[0] == current:
            return int(row[1])
        current, hops = row[0], hops + 1
    return None


def _component_size_compressing(conn: sqlite3.Connection, node: str) -> Optional[int]:
    root = _find(conn, node)
    if root is None:
        return None
    row = conn.execute("SELECT size FROM graph_components WHERE node = ?", (root,)).fetchone()
    return int(row[0]) if row else None


# ── Incremental maintenance ──────────────────────────────────────────────────

def refresh_payee(conn: sqlite3.Connection, vpa: str) -> None:
    """Recompute one payee's cached shape from its own edges.

    Bounded by that payee's payer count through ix_payers_vpa. Recomputing
    rather than adjusting in place is deliberate: an adjustment has to know
    whether the edge was new, whether it was this payer's second payment, and
    whether it moved the arrival window - three chances to drift out of step
    with the edge table after an unusual observation. One aggregate over a few
    dozen indexed rows costs less than the class of bug that avoids.
    """
    row = conn.execute(
        """
        SELECT COUNT(*)                      AS payers,
               COALESCE(SUM(payments > 1),0) AS repeats,
               COALESCE(SUM(payments),0)     AS payments,
               MIN(first_at)                 AS arrival_first,
               MAX(first_at)                 AS arrival_last,
               MIN(first_at)                 AS activity_first,
               MAX(last_at)                  AS activity_last
        FROM payee_payers WHERE vpa = ?
        """,
        (vpa,),
    ).fetchone()
    if not row or not row["payers"]:
        conn.execute("DELETE FROM payee_graph_cache WHERE vpa = ?", (vpa,))
        return

    conn.execute(
        """
        INSERT INTO payee_graph_cache
            (vpa, payer_count, repeat_payer_count, payments,
             arrival_first, arrival_last, activity_first, activity_last, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(vpa) DO UPDATE SET
            payer_count        = excluded.payer_count,
            repeat_payer_count = excluded.repeat_payer_count,
            payments           = excluded.payments,
            arrival_first      = excluded.arrival_first,
            arrival_last       = excluded.arrival_last,
            activity_first     = excluded.activity_first,
            activity_last      = excluded.activity_last,
            updated_at         = excluded.updated_at
        """,
        (vpa, row["payers"], row["repeats"], row["payments"], row["arrival_first"],
         row["arrival_last"], row["activity_first"], row["activity_last"],
         datetime.now(timezone.utc).isoformat()),
    )


def observe_edge(conn: sqlite3.Connection, vpa: str, payer_id: str) -> None:
    """Fold one observed payment into the graph structures.

    Called from record_payment INSIDE its transaction, so either the
    reputation row, the edge, the cached shape and the component all move
    together, or none of them do. Committing the edge and failing the cache
    would leave a payee whose shape says it has fewer payers than the edge
    table holds - a disagreement nothing downstream could detect.
    """
    refresh_payee(conn, vpa)
    union(conn, payer_id, vpa)


def backfill(conn: sqlite3.Connection) -> dict[str, int]:
    """Build both structures from edges already in the store.

    For deployments whose payee_payers predates this cache. Reads existing
    rows only; invents nothing.
    """
    ensure_schema(conn)
    edges = conn.execute("SELECT vpa, payer_id FROM payee_payers").fetchall()
    for edge in edges:
        union(conn, edge["payer_id"], edge["vpa"])
    payees = [r[0] for r in conn.execute("SELECT DISTINCT vpa FROM payee_payers")]
    for vpa in payees:
        refresh_payee(conn, vpa)
    return {"edges": len(edges), "payees": len(payees)}


# ── The read path ────────────────────────────────────────────────────────────

@dataclass
class GraphView:
    """What the pre-payment path can say about a payee's graph position.

    `available` is False when the payee has no cached row - it has never been
    observed - and the caller must report that rather than substituting zeros.
    A payee with no graph position is not a payee at the origin.
    """

    vpa: str
    available: bool = False
    unavailable_because: str = ""
    payer_count: Optional[int] = None
    repeat_payer_count: Optional[int] = None
    repeat_ratio: Optional[float] = None
    arrival_span_days: Optional[float] = None
    lifespan_days: Optional[float] = None
    payments_per_day: Optional[float] = None
    component_size: Optional[int] = None
    # Reported whenever a peer exists, because it is true and useful to see.
    shared_payer_peak: Optional[int] = None      # most payers shared with one other payee
    # None when the overlap carries no evidential weight - the peer keeps its
    # customers, or one side is too small to read. Informational, not absent:
    # shared_payer_peak still says what was observed.
    overlap_ratio: Optional[float] = None
    overlap_with: Optional[str] = None
    shape_findings: list[str] = field(default_factory=list)
    position_findings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "unavailable_because": self.unavailable_because or None,
            "payer_count": self.payer_count,
            "repeat_ratio": None if self.repeat_ratio is None else round(self.repeat_ratio, 3),
            "arrival_span_days": None if self.arrival_span_days is None
            else round(self.arrival_span_days, 2),
            "lifespan_days": None if self.lifespan_days is None else round(self.lifespan_days, 2),
            "payments_per_day": self.payments_per_day,
            "component_size": self.component_size,
            "shared_payer_peak": self.shared_payer_peak,
            "overlap_ratio": None if self.overlap_ratio is None else round(self.overlap_ratio, 3),
            "overlap_with": self.overlap_with,
            "shape_findings": self.shape_findings,
            "position_findings": self.position_findings,
        }


def _payer_overlap(conn: sqlite3.Connection, vpa: str, payer_count: int
                   ) -> tuple[Optional[int], Optional[float], Optional[str]]:
    """The payee sharing the most payers with this one.

    Two hops: this payee's payers, then the other payees those payers pay.
    Bounded by (payers of this payee) x (payees each of them pays), both small
    and both indexed. This is the one genuinely positional thing the read path
    computes - everything else above is local shape - and it is the evidence
    underneath ring detection without the all-pairs comparison ring detection
    needs.
    """
    if payer_count < MIN_SHARED_PAYERS:
        return None, None, None

    row = conn.execute(
        """
        SELECT other.vpa AS vpa, COUNT(*) AS shared
        FROM payee_payers mine
        JOIN payee_payers other ON other.payer_id = mine.payer_id AND other.vpa != mine.vpa
        WHERE mine.vpa = ?
        GROUP BY other.vpa
        ORDER BY shared DESC
        LIMIT 1
        """,
        (vpa,),
    ).fetchone()
    if row is None or not row["shared"]:
        return None, None, None

    # The peer's own shape decides whether this overlap means anything.
    #
    # Without this, a new shop whose four customers also use a large delivery
    # app scored a critical finding and blocked the payment: four shared
    # payers, four payers in total, ratio 1.0. The peer had a hundred and
    # twenty payers and every one of them a repeat customer. detect_rings
    # never had this bug - it requires BOTH payees to be in its one-shot
    # `eligible` set, and this function dropped that half of the rule. Sharing
    # customers with a popular merchant is what being a shop in the same
    # street looks like.
    peer = conn.execute(
        """
        SELECT c.payer_count AS payers, c.repeat_payer_count AS repeats
        FROM payee_graph_cache c WHERE c.vpa = ?
        """,
        (row["vpa"],),
    ).fetchone()
    if peer is None or not peer["payers"]:
        return None, None, None

    peer_payers = int(peer["payers"])
    peer_repeat_ratio = peer["repeats"] / max(peer_payers, 1)
    if peer_repeat_ratio >= ONE_SHOT_RATIO:
        # A peer that keeps its customers is a merchant, not a co-collector.
        return int(row["shared"]), None, row["vpa"]
    if min(payer_count, peer_payers) < MIN_PAYERS_FOR_OVERLAP:
        # Too few payers on one side for the one-shot reading to be evidence.
        return int(row["shared"]), None, row["vpa"]

    smallest = min(payer_count, peer_payers) or 1
    return int(row["shared"]), row["shared"] / smallest, row["vpa"]


def graph_view(conn: sqlite3.Connection, vpa: str) -> GraphView:
    """Read the maintained features. No rebuild, and no writes of any kind.

    Deliberately does NOT call ensure_schema. A read path that creates tables
    is a read path that writes, which breaks the rule that checking a payment
    never changes anything - and on a network-mounted database file the DDL on
    every check was enough to produce I/O errors outright. The schema is
    created once by connect(); a missing table here means the store was never
    initialised, and the honest answer to that is that the feature is
    unavailable.
    """
    # Normalise, as assess_payee does. The store keys on the normalised form,
    # so a caller passing the address as the user typed it would silently miss
    # the row and be told the payee has never been observed.
    vpa = normalise_vpa(vpa)
    view = GraphView(vpa=vpa)

    try:
        row = conn.execute("SELECT * FROM payee_graph_cache WHERE vpa = ?", (vpa,)).fetchone()
    except sqlite3.OperationalError:
        view.unavailable_because = (
            "The graph cache has not been initialised in this store. Run "
            "scripts/bootstrap_payee_reputation.py --backfill-graph."
        )
        return view

    if row is None:
        view.unavailable_because = (
            "This address has never been observed in contributed transaction "
            "data, so it has no position in the payment graph."
        )
        return view

    view.available = True
    view.payer_count = row["payer_count"]
    view.repeat_payer_count = row["repeat_payer_count"]
    view.repeat_ratio = row["repeat_payer_count"] / max(row["payer_count"], 1)
    view.arrival_span_days = _days(row["arrival_first"], row["arrival_last"])
    view.lifespan_days = _days(row["activity_first"], row["activity_last"])
    if view.lifespan_days is not None:
        view.payments_per_day = round(row["payments"] / max(view.lifespan_days, 1.0), 2)
    view.component_size = component_size(conn, vpa)

    shared, ratio, peer = _payer_overlap(conn, vpa, row["payer_count"])
    view.shared_payer_peak, view.overlap_ratio, view.overlap_with = shared, ratio, peer

    # ── Shape: what the money did. Same thresholds as fraud_graph. ──────────
    fan_in = row["payer_count"]
    if fan_in >= MIN_FAN_IN and view.repeat_ratio < ONE_SHOT_RATIO:
        view.shape_findings.append(
            f"{fan_in} different people have paid this address and "
            f"{'none' if view.repeat_ratio == 0 else 'almost none'} paid twice."
        )
    if (view.arrival_span_days is not None and view.arrival_span_days <= BURST_WINDOW_DAYS
            and fan_in >= MIN_FAN_IN):
        view.shape_findings.append(
            f"All {fan_in} payers arrived within {view.arrival_span_days:.0f} days."
        )
    if view.payments_per_day is not None and view.payments_per_day >= 5 and fan_in >= MIN_FAN_IN:
        view.shape_findings.append(
            f"Averaging {view.payments_per_day} payments a day from new payers."
        )

    # ── Position: where it sits relative to other addresses. ────────────────
    # Only overlap earns this. Component size on its own says nothing - every
    # address in a connected payment network belongs to one large component,
    # and reporting that as a finding would flag the whole graph.
    if (shared is not None and shared >= MIN_SHARED_PAYERS and ratio is not None
            and ratio >= OVERLAP_RATIO and view.repeat_ratio < ONE_SHOT_RATIO):
        view.position_findings.append(
            f"{shared} of this address's {fan_in} payers also pay {peer}, and almost "
            f"nobody pays either of them twice. Independent merchants keep their own "
            f"customers; collection accounts share them."
        )

    return view


def graph_limitations() -> list[str]:
    """Stated rather than left to be discovered."""
    return [
        "Ring detection (fraud_graph.detect_rings) compares every eligible payee "
        "against every other and has no incremental form, so it stays on the "
        "dashboard path. The pre-payment check reports the pairwise payer overlap "
        "that underlies a ring, not ring membership itself.",
        "Component size is maintained by union-find, which is correct while "
        "observations only add edges. Removing an edge would require a rebuild; "
        "nothing in the system removes one.",
        "Overlap is computed against the single strongest peer, not the full peer "
        "set, to keep the read bounded.",
    ]
