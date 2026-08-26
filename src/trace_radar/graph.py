"""Sample LAN graph plus topology built from traceroute hops."""

from __future__ import annotations

from typing import Any

SLOW_HINT = 25.0

# Scanny-style local network sample so the force graph is never an empty line.
SAMPLE_LAN: list[dict[str, Any]] = [
    {
        "id": "lan:you",
        "label": "This host",
        "kind": "host",
        "ip": "192.168.1.42",
        "vendor": "local",
        "layer": 0,
    },
    {
        "id": "lan:phone",
        "label": "iPhone",
        "kind": "phone",
        "ip": "192.168.1.64",
        "vendor": "Apple",
        "layer": 0,
    },
    {
        "id": "lan:nas",
        "label": "NAS",
        "kind": "nas",
        "ip": "192.168.1.10",
        "vendor": "Synology",
        "layer": 0,
    },
    {
        "id": "lan:ap",
        "label": "Access point",
        "kind": "ap",
        "ip": "192.168.1.2",
        "vendor": "UniFi",
        "layer": 0,
    },
    {
        "id": "lan:tv",
        "label": "Apple TV",
        "kind": "media",
        "ip": "192.168.1.80",
        "vendor": "Apple",
        "layer": 0,
    },
]


def hop_node_id(hop: dict[str, Any], *, target: str) -> str:
    ip = hop.get("ip")
    if ip:
        return f"ip:{ip}"
    return f"star:{target}:{hop.get('ttl')}"


def build_topology(
    routes: list[dict[str, Any]],
    *,
    origin: dict[str, Any] | None = None,
    lan: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge LAN sample devices and traceroute hops into a force-graph payload."""
    lan_nodes = list(lan if lan is not None else SAMPLE_LAN)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    edge_seen: set[tuple[str, str]] = set()

    def upsert(node_id: str, **fields: Any) -> dict[str, Any]:
        existing = nodes.get(node_id)
        if existing is None:
            node = {"id": node_id, "targets": [], "search": ""}
            node.update({k: v for k, v in fields.items() if v is not None})
            nodes[node_id] = node
            return node
        for key, value in fields.items():
            if value is None:
                continue
            if key == "targets" and isinstance(value, list):
                for item in value:
                    if item not in existing["targets"]:
                        existing["targets"].append(item)
                continue
            if key in existing and existing[key] not in (None, "", []):
                continue
            existing[key] = value
        return existing

    origin_id = "lan:you"
    upsert(
        origin_id,
        label=(origin or {}).get("org") or "This host",
        kind="host",
        ip=(origin or {}).get("ip") or "192.168.1.42",
        layer=0,
        health="good",
        city=(origin or {}).get("city"),
        country=(origin or {}).get("country"),
        asn=(origin or {}).get("asn"),
        provider=(origin or {}).get("isp") or (origin or {}).get("org"),
    )
    for device in lan_nodes:
        if device["id"] == origin_id:
            continue
        upsert(
            device["id"],
            label=device.get("label"),
            kind=device.get("kind") or "host",
            ip=device.get("ip"),
            vendor=device.get("vendor"),
            layer=0,
            health="good",
        )

    gateway_id: str | None = None
    for route in routes:
        hops = route.get("hops") or []
        target = route.get("target") or ""
        prev_id = origin_id
        for hop in hops:
            node_id = hop_node_id(hop, target=target)
            kind = "dest" if hop.get("ttl") == len(hops) else "hop"
            if hop.get("is_private"):
                kind = "gateway" if hop.get("ttl") == 1 else "router"
                if gateway_id is None and hop.get("ttl") == 1:
                    gateway_id = node_id
            whois = hop.get("whois") or {}
            geo = hop.get("geo") or {}
            upsert(
                node_id,
                label=hop.get("hostname") or hop.get("ip") or f"hop {hop.get('ttl')}",
                kind=kind,
                ip=hop.get("ip"),
                hostname=hop.get("hostname"),
                ttl=hop.get("ttl"),
                health=hop.get("health"),
                rtt_ms=hop.get("rtt_avg_ms"),
                added_ms=hop.get("added_ms"),
                loss_pct=hop.get("last_loss_pct"),
                slow=hop.get("slow"),
                problem_reason=hop.get("problem_reason"),
                icmp_filtered=hop.get("icmp_filtered"),
                asn=whois.get("asn") or geo.get("asn"),
                provider=whois.get("org") or geo.get("isp") or geo.get("org"),
                cidr=whois.get("cidr"),
                city=geo.get("city"),
                country=geo.get("country"),
                place=geo.get("place"),
                layer=int(hop.get("ttl") or 1) + 1,
                targets=[target],
            )
            _add_edge(
                edges,
                edge_seen,
                prev_id,
                node_id,
                rtt_ms=hop.get("rtt_avg_ms"),
                added_ms=hop.get("added_ms"),
                slow=bool(hop.get("slow")),
                kind="path",
                label=_edge_label(hop),
            )
            prev_id = node_id

    if gateway_id is None:
        gateway_id = "lan:gw"
        upsert(gateway_id, label="Home gateway", kind="gateway", ip="192.168.1.1", layer=1, health="good")

    for device in lan_nodes:
        _add_edge(edges, edge_seen, device["id"], gateway_id, kind="lan", label="LAN", rtt_ms=0.4)

    for node in nodes.values():
        parts = [
            node.get("label"),
            node.get("ip"),
            node.get("hostname"),
            node.get("asn"),
            node.get("provider"),
            node.get("city"),
            node.get("kind"),
        ]
        node["search"] = " ".join(str(part) for part in parts if part).lower()

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "lan_count": len(lan_nodes),
        "hop_node_count": sum(1 for node in nodes.values() if str(node["id"]).startswith(("ip:", "star:"))),
    }


def _edge_label(hop: dict[str, Any]) -> str:
    if hop.get("icmp_filtered"):
        return "filtered"
    if not hop.get("responded"):
        return "timeout"
    added = hop.get("added_ms")
    rtt = hop.get("rtt_avg_ms")
    if added is not None and added >= SLOW_HINT:
        return f"+{added:.0f} ms"
    if rtt is not None:
        return f"{rtt:.0f} ms"
    return ""


def _add_edge(
    edges: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    source: str,
    target: str,
    *,
    kind: str,
    label: str = "",
    rtt_ms: float | None = None,
    added_ms: float | None = None,
    slow: bool = False,
) -> None:
    key = (source, target)
    if source == target or key in seen:
        return
    seen.add(key)
    edges.append(
        {
            "source": source,
            "target": target,
            "kind": kind,
            "label": label,
            "rtt_ms": rtt_ms,
            "added_ms": added_ms,
            "slow": slow,
        }
    )
