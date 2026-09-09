"""Graph analysis over the payer -> payee network.

The implementation these replace returned every node with degree >= 3, which
on real data returns the most popular merchants and reports payers as if they
were merchants. These tests pin down the difference.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.services.fraud_graph import (
    Edge,
    build_graph,
    detect_rings,
    payees,
    payers,
    signals_for,
    suspicious_payees,
)


def _at(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _merchant(name: str, n_payers: int = 20, repeat: bool = True) -> list[Edge]:
    """A real merchant: built up over a year, customers come back."""
    return [
        Edge(f"cust_{i}", name, 6 if repeat else 1, _at(365 - i * 10), _at(5))
        for i in range(n_payers)
    ]


def _collector(name: str, n_payers: int = 20, days: int = 8) -> list[Edge]:
    """A collection account: many payers, all at once, none return."""
    return [
        Edge(f"victim_{name}_{i}", name, 1, _at(days - i * 0.2), _at(days - i * 0.2))
        for i in range(n_payers)
    ]


# ── The two sides of the graph must not be confused ───────────────────────

def test_payers_and_payees_are_kept_separate():
    g = build_graph(_merchant("shop@okaxis", 5))
    assert payees(g) == ["shop@okaxis"]
    assert len(payers(g)) == 5
    assert "shop@okaxis" not in payers(g)


# ── Popularity is not fraud ───────────────────────────────────────────────

def test_a_popular_merchant_is_not_flagged():
    """The old rule flagged anything with degree >= 3, so every busy merchant
    was 'suspicious'."""
    flagged = suspicious_payees(_merchant("swiggy@ibl", n_payers=40))
    assert flagged == []


def test_a_collection_account_is_flagged_with_reasons():
    flagged = suspicious_payees(_collector("mule@ybl"))
    assert len(flagged) == 1
    assert flagged[0]["node"] == "mule@ybl"
    assert flagged[0]["reasons"], "a flagged node must say why"


def test_flagged_and_unflagged_can_coexist():
    edges = _merchant("swiggy@ibl", 40) + _collector("mule@ybl")
    nodes = {d["node"] for d in suspicious_payees(edges)}
    assert nodes == {"mule@ybl"}


# ── Rings ─────────────────────────────────────────────────────────────────

def test_a_household_paying_the_same_shops_is_not_a_ring():
    """Three people who all shop at the same four local businesses share a
    payer pool completely, and are not a fraud ring. Repeat custom is what
    separates them."""
    edges = []
    for shop in ("kirana@okaxis", "restaurant@ybl", "chemist@paytm", "salon@okaxis"):
        for i in range(4):
            edges.append(Edge(f"family_{i}", shop, 8, _at(300), _at(2)))
    assert detect_rings(edges) == []


def test_addresses_sharing_a_one_shot_payer_pool_are_a_ring():
    edges = []
    for addr in ("ring-a@ybl", "ring-b@ybl", "ring-c@okaxis"):
        for i in range(6):
            edges.append(Edge(f"victim_{i}", addr, 1, _at(4), _at(3)))
    rings = detect_rings(edges)
    assert len(rings) == 1
    assert set(rings[0].payees) == {"ring-a@ybl", "ring-b@ybl", "ring-c@okaxis"}
    assert len(rings[0].shared_payers) == 6
    assert rings[0].reason


def test_two_unrelated_collectors_are_not_one_ring():
    edges = _collector("a@ybl") + _collector("b@ybl")   # disjoint victim sets
    assert detect_rings(edges) == []


# ── Per-node signals ──────────────────────────────────────────────────────

def test_signals_describe_a_merchant_correctly():
    edges = _merchant("shop@okaxis", 10)
    s = signals_for("shop@okaxis", build_graph(edges), edges)
    assert s.fan_in == 10
    assert s.repeat_ratio == 1.0
    assert s.findings == []


def test_signals_describe_a_collector_correctly():
    edges = _collector("mule@ybl", 15, days=6)
    s = signals_for("mule@ybl", build_graph(edges), edges)
    assert s.fan_in == 15
    assert s.repeat_ratio == 0.0
    assert s.lifespan_days is not None and s.lifespan_days <= 7
    assert len(s.findings) >= 2


def test_a_payer_spraying_many_addresses_is_flagged():
    edges = [Edge("compromised", f"payee_{i}@ybl", 1, _at(3), _at(1)) for i in range(20)]
    s = signals_for("compromised", build_graph(edges), edges)
    assert s.fan_out == 20
    assert any("compromised account" in f for f in s.findings)


@pytest.mark.parametrize("n_payers,expect_flagged", [(3, False), (9, False), (12, True)])
def test_flagging_needs_enough_payers_to_mean_something(n_payers, expect_flagged):
    flagged = suspicious_payees(_collector("x@ybl", n_payers=n_payers))
    assert bool(flagged) is expect_flagged
