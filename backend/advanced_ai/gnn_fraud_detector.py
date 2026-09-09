"""Retired.

This module was presented as GNN fraud detection. It contained no neural
network: it returned every node with degree >= 3, which on real data returns
the most popular merchants.

The real implementation is backend/app/services/fraud_graph.py, which works on
the persisted payer -> payee edges and attaches a reason to every result.
"""

from backend.app.services.fraud_graph import load_edges, suspicious_payees


def gnn_risk(edges=None):  # noqa: ARG001 - signature kept for old callers
    """Deprecated. Use fraud_graph.suspicious_payees()."""
    return [d["node"] for d in suspicious_payees(load_edges())]
