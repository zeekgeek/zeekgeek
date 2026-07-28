"""Relationship-hypothesis graph construction and interactive rendering."""

from __future__ import annotations

from itertools import combinations
from typing import Iterable

import matplotlib.pyplot as plt
import networkx as nx

from scanner import DiscoveredDevice


def _edge_evidence(
    left: DiscoveredDevice, right: DiscoveredDevice
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    # Both signals being strong means both are near this scanner.  It does not
    # prove that the two peripherals are near or connected to each other.
    if left.rssi > -70 and right.rssi > -70:
        score += 0.25
        reasons.append("both near observer")

    shared_services = left.service_uuids & right.service_uuids
    if shared_services:
        score += min(0.45, 0.20 + 0.05 * len(shared_services))
        reasons.append(f"{len(shared_services)} shared service(s)")

    shared_ecosystems = left.ecosystems & right.ecosystems
    if shared_ecosystems:
        score += 0.45
        reasons.append("shared " + ", ".join(sorted(shared_ecosystems)))

    return min(score, 1.0), reasons


def build_relationship_graph(
    devices: Iterable[DiscoveredDevice],
) -> nx.Graph:
    graph = nx.Graph()
    device_list = list(devices)
    for device in device_list:
        graph.add_node(
            device.address,
            label=device.display_name,
            hidden=device.identity_limited,
            rssi=device.rssi,
            ecosystems=sorted(device.ecosystems),
            details=device.as_dict(),
        )

    for left, right in combinations(device_list, 2):
        weight, evidence = _edge_evidence(left, right)
        if weight >= 0.25:
            graph.add_edge(
                left.address,
                right.address,
                weight=round(weight, 2),
                evidence=evidence,
            )
    return graph


def show_interactive_graph(graph: nx.Graph) -> None:
    """Open a Matplotlib graph; clicking nodes shows complete observations."""
    if not graph:
        return
    figure, axis = plt.subplots(figsize=(12, 8))
    figure.canvas.manager.set_window_title("BluetoothRadar relationship hypotheses")
    positions = nx.spring_layout(graph, seed=42, weight="weight")
    nodes = list(graph.nodes)
    node_artist = nx.draw_networkx_nodes(
        graph,
        positions,
        ax=axis,
        node_color=[
            "#ef4444" if graph.nodes[node]["hidden"] else "#38bdf8"
            for node in nodes
        ],
        node_size=950,
    )
    node_artist.set_picker(True)
    nx.draw_networkx_labels(
        graph,
        positions,
        labels={node: graph.nodes[node]["label"] for node in nodes},
        font_size=8,
        ax=axis,
    )
    widths = [
        1 + 4 * graph.edges[edge]["weight"] for edge in graph.edges
    ]
    nx.draw_networkx_edges(
        graph, positions, width=widths, alpha=0.55, edge_color="#64748b", ax=axis
    )
    nx.draw_networkx_edge_labels(
        graph,
        positions,
        edge_labels={
            (left, right): f'{attrs["weight"]:.2f}'
            for left, right, attrs in graph.edges(data=True)
        },
        font_size=7,
        ax=axis,
    )
    annotation = axis.annotate(
        "",
        xy=(0, 0),
        xytext=(15, 15),
        textcoords="offset points",
        bbox={"boxstyle": "round", "fc": "white", "alpha": 0.95},
        fontsize=8,
    )
    annotation.set_visible(False)

    def on_pick(event: object) -> None:
        indices = getattr(event, "ind", [])
        if not indices:
            return
        node = nodes[indices[0]]
        attrs = graph.nodes[node]
        details = attrs["details"]
        incident = [
            f'{neighbor}: {graph.edges[node, neighbor]["weight"]:.2f}'
            for neighbor in graph.neighbors(node)
        ]
        text = (
            f'{attrs["label"]}\nIdentifier: {node}\nRSSI: {attrs["rssi"]} dBm\n'
            f'Hidden flag: {attrs["hidden"]}\n'
            f'Services: {", ".join(details["service_uuids"]) or "none"}\n'
            f'Ecosystems: {", ".join(attrs["ecosystems"]) or "none"}\n'
            f'Edges: {"; ".join(incident) or "none"}'
        )
        annotation.xy = positions[node]
        annotation.set_text(text)
        annotation.set_visible(True)
        figure.canvas.draw_idle()

    figure.canvas.mpl_connect("pick_event", on_pick)
    axis.set_title(
        "Inferred BLE relationships (heuristics, not observed pairings)\n"
        "Red = identity-limited advertisement; click a node for details"
    )
    axis.axis("off")
    figure.tight_layout()
    plt.show()

