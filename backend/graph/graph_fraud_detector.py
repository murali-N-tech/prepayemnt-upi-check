import networkx as nx

fraud_graph = nx.Graph()


def add_connection(user, merchant):

    fraud_graph.add_node(user, type="user")
    fraud_graph.add_node(merchant, type="merchant")

    fraud_graph.add_edge(user, merchant)


def get_graph():

    edges = []

    for u, v in fraud_graph.edges():
        edges.append({"user": u, "merchant": v})

    return edges


def detect_fraud_rings():
    """Deprecated. Use backend.app.services.fraud_graph.detect_rings().

    This walked every node in the in-memory graph, so a *payer* with three
    merchants was reported as a merchant ring, and any popular merchant was
    reported because popularity raises degree. It is kept only so old callers
    do not break; it now returns nothing rather than noise.
    """
    return []