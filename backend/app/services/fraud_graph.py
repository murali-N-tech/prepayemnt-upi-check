"""Graph analysis over the persisted payer -> payee edges.

What was here before called itself GNN fraud detection and returned every node
with degree >= 3. On a real dataset that returns Swiggy: a popular merchant has
a high degree because it is popular. Degree is a measure of success, not fraud.

What actually separates a fraud ring from a busy merchant is the *shape* of the
bipartite payer/payee graph:

  - a merchant accumulates payers gradually and keeps them (payers return)
  - a collection account accumulates payers in a burst and loses them all
  - several addresses run by one operator share an unusual number of payers

None of that is visible from a degree count, and all of it is visible from the
payee_payers edge list the reputation store maintains.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Optional

import networkx as nx

from backend.app.services.payee_reputation import connect


@dataclass
class Edge:
    payer: str
    payee: str
    payments: int
    first_at: str
    last_at: str


@dataclass
class Ring:
    payees: list[str]
    shared_payers: list[str]
    overlap: float                  # shared payers / smallest payee's payer set
    total_payments: int
    reason: str


@dataclass
class GraphSignals:
    node: str
    fan_in: int = 0                 # payees only: how many people paid it
    fan_out: int = 0                # payers only: how many payees they paid
    repeat_ratio: float = 0.0       # share of payers who paid more than once
    lifespan_days: Optional[int] = None
    payments_per_day: Optional[float] = None
    component_size: int = 0
    findings: list[str] = field(default_factory=list)


def _parse(ts: str | None) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_edges(conn: Optional[sqlite3.Connection] = None) -> list[Edge]:
    own = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT vpa, payer_id, payments, first_at, last_at FROM payee_payers"
        ).fetchall()
    finally:
        if own:
            conn.close()
    return [Edge(r["payer_id"], r["vpa"], r["payments"], r["first_at"], r["last_at"]) for r in rows]


def build_graph(edges: list[Edge]) -> nx.Graph:
    """Bipartite graph. Node type is stored so the two sides are never mixed -
    the previous ring detector walked every node and reported payers as if they
    were merchants."""
    g = nx.Graph()
    for e in edges:
        g.add_node(e.payer, kind="payer")
        g.add_node(e.payee, kind="payee")
        g.add_edge(e.payer, e.payee, payments=e.payments,
                   first_at=e.first_at, last_at=e.last_at)
    return g


def payees(g: nx.Graph) -> list[str]:
    return [n for n, d in g.nodes(data=True) if d.get("kind") == "payee"]


def payers(g: nx.Graph) -> list[str]:
    return [n for n, d in g.nodes(data=True) if d.get("kind") == "payer"]


def detect_rings(
    edges: list[Edge],
    min_shared_payers: int = 4,
    min_overlap: float = 0.6,
    max_repeat_ratio: float = 0.2,
) -> list[Ring]:
    """Payees that draw from an overlapping pool of payers.

    One person paying two shops proves nothing, and neither does a household
    paying the same four local shops - shared payers alone produce exactly that
    false positive. A ring needs the overlap AND the collection shape: payers
    who pay once and never return.

    So only one-shot payees are eligible. A merchant with returning customers
    is excluded however much its customer base overlaps with another's.
    """
    payers_of: dict[str, set[str]] = defaultdict(set)
    payments_of: dict[str, int] = defaultdict(int)
    repeat_of: dict[str, int] = defaultdict(int)
    for e in edges:
        payers_of[e.payee].add(e.payer)
        payments_of[e.payee] += e.payments
        if e.payments > 1:
            repeat_of[e.payee] += 1

    eligible = {
        payee
        for payee, ps in payers_of.items()
        if len(ps) >= min_shared_payers
        and repeat_of[payee] / max(len(ps), 1) <= max_repeat_ratio
    }

    # Link payees that share enough payers.
    linked = nx.Graph()
    for a, b in combinations(sorted(eligible), 2):
        shared = payers_of[a] & payers_of[b]
        if len(shared) < min_shared_payers:
            continue
        overlap = len(shared) / min(len(payers_of[a]), len(payers_of[b]))
        if overlap >= min_overlap:
            linked.add_edge(a, b, shared=shared, overlap=overlap)

    rings: list[Ring] = []
    for component in nx.connected_components(linked):
        group = sorted(component)
        shared = set.intersection(*(payers_of[p] for p in group))
        if len(shared) < min_shared_payers:
            continue
        overlaps = [linked[a][b]["overlap"] for a, b in combinations(group, 2) if linked.has_edge(a, b)]
        rings.append(
            Ring(
                payees=group,
                shared_payers=sorted(shared),
                overlap=round(sum(overlaps) / len(overlaps), 3) if overlaps else 1.0,
                total_payments=sum(payments_of[p] for p in group),
                reason=(
                    f"{len(group)} addresses are paid by the same {len(shared)} "
                    f"people, and almost nobody pays any of them twice. "
                    f"Independent merchants keep customers; collection accounts "
                    f"share them."
                ),
            )
        )
    return sorted(rings, key=lambda r: (-len(r.payees), -len(r.shared_payers)))


def signals_for(node: str, g: nx.Graph, edges: list[Edge]) -> GraphSignals:
    s = GraphSignals(node=node)
    if node not in g:
        return s

    kind = g.nodes[node].get("kind")
    neighbours = list(g.neighbors(node))
    incident = [e for e in edges if (e.payee == node if kind == "payee" else e.payer == node)]

    if kind == "payee":
        s.fan_in = len(neighbours)
        repeat = sum(1 for e in incident if e.payments > 1)
        s.repeat_ratio = round(repeat / max(len(incident), 1), 3)
    else:
        s.fan_out = len(neighbours)

    firsts = [d for d in (_parse(e.first_at) for e in incident) if d]
    lasts = [d for d in (_parse(e.last_at) for e in incident) if d]
    if firsts and lasts:
        s.lifespan_days = max(0, (max(lasts) - min(firsts)).days)
        total = sum(e.payments for e in incident)
        s.payments_per_day = round(total / max(s.lifespan_days, 1), 2)

    component = nx.node_connected_component(g, node)
    s.component_size = len(component)

    # ── Findings, each with the reasoning attached ────────────────────────
    if kind == "payee":
        if s.fan_in >= 10 and s.repeat_ratio < 0.1:
            s.findings.append(
                f"{s.fan_in} different people have paid this address and "
                f"{'none' if s.repeat_ratio == 0 else 'almost none'} paid twice."
            )
        if s.lifespan_days is not None and s.lifespan_days <= 30 and s.fan_in >= 10:
            s.findings.append(
                f"All {s.fan_in} payers arrived within {s.lifespan_days} days."
            )
        if s.payments_per_day is not None and s.payments_per_day >= 5 and s.fan_in >= 10:
            s.findings.append(
                f"Averaging {s.payments_per_day} payments a day from new payers."
            )
    else:
        if s.fan_out >= 15 and s.lifespan_days is not None and s.lifespan_days <= 7:
            s.findings.append(
                f"This payer sent money to {s.fan_out} different addresses in "
                f"{s.lifespan_days} days, which is what a compromised account looks like."
            )

    return s


def suspicious_payees(edges: list[Edge], limit: int = 25) -> list[dict[str, Any]]:
    """Replaces the old degree >= 3 rule. Only returns nodes with a stated reason."""
    g = build_graph(edges)
    out: list[dict[str, Any]] = []
    for node in payees(g):
        s = signals_for(node, g, edges)
        if not s.findings:
            continue
        out.append(
            {
                "node": node,
                "kind": "payee",
                "fan_in": s.fan_in,
                "repeat_ratio": s.repeat_ratio,
                "lifespan_days": s.lifespan_days,
                "payments_per_day": s.payments_per_day,
                "reasons": s.findings,
            }
        )
    out.sort(key=lambda d: (-len(d["reasons"]), -d["fan_in"]))
    return out[:limit]


def graph_summary(conn: Optional[sqlite3.Connection] = None) -> dict[str, Any]:
    edges = load_edges(conn)
    g = build_graph(edges)
    rings = detect_rings(edges)
    return {
        "payers": len(payers(g)),
        "payees": len(payees(g)),
        "edges": len(edges),
        "components": nx.number_connected_components(g) if len(g) else 0,
        "rings": [
            {
                "payees": r.payees,
                "shared_payers": r.shared_payers,
                "overlap": r.overlap,
                "total_payments": r.total_payments,
                "reason": r.reason,
            }
            for r in rings
        ],
        "suspicious": suspicious_payees(edges),
    }
