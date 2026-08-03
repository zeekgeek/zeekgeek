"""Graph intelligence for BLE relationship hypotheses."""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx


@dataclass
class GraphReport:
    hubs: list[tuple[str, float]] = field(default_factory=list)
    clusters: list[set[str]] = field(default_factory=list)
    multi_cluster_devices: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def _clusters(graph: nx.Graph) -> list[set[str]]:
    if graph.number_of_nodes() < 2 or graph.number_of_edges() == 0:
        return [{node} for node in graph.nodes]
    try:
        communities = nx.community.louvain_communities(
            graph, weight="weight", seed=42
        )
    except AttributeError:
        communities = nx.community.greedy_modularity_communities(
            graph, weight="weight"
        )
    return [set(community) for community in communities]


def analyze_graph(graph: nx.Graph) -> GraphReport:
    if not graph:
        return GraphReport()

    centrality = nx.degree_centrality(graph)
    max_degree = max(centrality.values(), default=0.0)
    hubs = sorted(
        [
            (node, score)
            for node, score in centrality.items()
            if score == max_degree and score > 0
        ],
        key=lambda item: item[0],
    )
    clusters = _clusters(graph)

    # Clique communities overlap, unlike Louvain's partition, and therefore
    # provide a meaningful "multiple clusters" signal.
    overlapping = (
        [set(group) for group in nx.community.k_clique_communities(graph, 3)]
        if graph.number_of_nodes() >= 3
        else []
    )
    membership: dict[str, int] = {}
    for community in overlapping:
        for node in community:
            membership[node] = membership.get(node, 0) + 1
    multi_cluster = sorted(
        node for node, count in membership.items() if count > 1
    )

    suggestions: list[str] = []
    for hub, _ in hubs:
        hub_label = graph.nodes[hub]["label"]
        for neighbor in graph.neighbors(hub):
            attrs = graph.edges[hub, neighbor]
            reasons = ", ".join(attrs.get("evidence", []))
            neighbor_label = graph.nodes[neighbor]["label"]
            suggestions.append(
                f"{hub_label} may share an ecosystem context with "
                f"{neighbor_label} ({reasons}); pairing is not confirmed."
            )

    return GraphReport(
        hubs=hubs,
        clusters=clusters,
        multi_cluster_devices=multi_cluster,
        suggestions=suggestions,
    )

