"""Demo LAN + multi-path internet topology (sample graph data)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .providers import enrich_dict

LAN_NODE_BY_IP = {
    "192.168.1.42": "lan:you",
    "192.168.1.1": "lan:gw",
    "192.168.1.2": "lan:ap",
    "192.168.1.10": "lan:nas",
    "192.168.1.64": "lan:phone",
    "192.168.1.80": "lan:tv",
}


def node_id_for(
    ip: str | None,
    hop: int | None = None,
    *,
    gateway_ip: str | None = None,
    local_ips: set[str] | None = None,
) -> str:
    if ip and local_ips and ip in local_ips:
        return "lan:you"
    if ip and gateway_ip and ip == gateway_ip:
        return "lan:gw"
    if ip and ip in LAN_NODE_BY_IP:
        return LAN_NODE_BY_IP[ip]
    if ip:
        return f"net:{ip}"
    return f"hop:{hop or 0}"


@dataclass(frozen=True)
class HopTemplate:
    hop: int
    ip: str | None
    hostname: str | None
    base_rtt: float
    jitter: float
    loss: float
    asn: str
    role: str
    city: str | None
    layer: int
    facility: str | None = None
    problem: bool = False
    notes: str | None = None

    @property
    def node_id(self) -> str:
        return node_id_for(self.ip, self.hop)


@dataclass(frozen=True)
class LanDevice:
    id: str
    name: str
    ip: str
    kind: str
    vendor: str
    layer: int = 0
    notes: str | None = None


# Shared access/metro hops (Comcast Seattle metro).
GW = HopTemplate(
    1,
    "192.168.1.1",
    "u6-gateway.lan",
    base_rtt=0.55,
    jitter=0.12,
    loss=0.0,
    asn="PRIVATE",
    role="gateway",
    city="LAN",
    layer=1,
    notes="Home gateway. Sub-millisecond is healthy.",
)
ONT = HopTemplate(
    2,
    "10.4.0.1",
    "ont.hfc.home",
    base_rtt=1.9,
    jitter=0.35,
    loss=0.0,
    asn="CGNAT",
    role="access",
    city="Last mile",
    layer=2,
    notes="HFC / ONT. Still inside the ISP last mile.",
)
RUR = HopTemplate(
    3,
    "96.120.88.141",
    "po-100-x3607-rur101.seattle.wa.seattle.comcast.net",
    base_rtt=8.4,
    jitter=1.1,
    loss=0.0,
    asn="AS7922",
    role="access",
    city="Seattle, WA",
    layer=3,
    facility="Comcast rural/metro RUR",
)
AR = HopTemplate(
    4,
    "68.87.194.37",
    "ae-21-0-ar01.seattle.wa.seattle.comcast.net",
    base_rtt=11.2,
    jitter=1.4,
    loss=0.0,
    asn="AS7922",
    role="metro",
    city="Seattle, WA",
    layer=4,
    facility="Comcast aggregation router",
)
CR = HopTemplate(
    5,
    "68.86.90.5",
    "be-336-cr02.seattle.wa.seattle.comcast.net",
    base_rtt=13.6,
    jitter=1.6,
    loss=0.002,
    asn="AS7922",
    role="metro",
    city="Seattle, WA",
    layer=4,
    facility="Comcast core",
    notes="Last Comcast hop before off-net peering.",
)

# The problem router: first Cogent hop after the Comcast handoff.
COGENT_SEA = HopTemplate(
    6,
    "154.54.30.17",
    "be2993.ccr42.sea02.atlas.cogentco.com",
    base_rtt=88.0,
    jitter=16.0,
    loss=0.08,
    asn="AS174",
    role="peering",
    city="Seattle, WA",
    layer=5,
    facility="Westin Building Meet-Me / Cogent SEA02",
    problem=True,
    notes="Peering handoff Comcast → Cogent. This is where delay enters the path.",
)
COGENT_SFO = HopTemplate(
    7,
    "154.54.42.90",
    "be2693.ccr21.sfo01.atlas.cogentco.com",
    base_rtt=92.5,
    jitter=14.0,
    loss=0.03,
    asn="AS174",
    role="transit",
    city="San Francisco, CA",
    layer=6,
    facility="Cogent SFO01 atlas core",
    notes="Long-haul Cogent. Inherits SEA02 delay; adds very little of its own.",
)
COGENT_EDGE = HopTemplate(
    8,
    "154.54.31.74",
    "te0-0-1-1.ccr21.sfo01.atlas.cogentco.com",
    base_rtt=94.0,
    jitter=13.0,
    loss=0.02,
    asn="AS174",
    role="transit",
    city="San Francisco, CA",
    layer=6,
    facility="Cogent → off-net edge",
)
CF_DEST = HopTemplate(
    9,
    "1.1.1.1",
    "one.one.one.one",
    base_rtt=96.4,
    jitter=12.0,
    loss=0.01,
    asn="AS13335",
    role="anycast",
    city="Anycast edge",
    layer=7,
    notes="Cloudflare DNS. Fast when not stuck behind Cogent.",
)
GH_DEST = HopTemplate(
    8,
    "140.82.112.3",
    "lb-140-82-112-3-iad.github.com",
    base_rtt=98.8,
    jitter=12.5,
    loss=0.01,
    asn="AS36459",
    role="anycast",
    city="IAD / Anycast",
    layer=7,
    notes="GitHub. Shares the Cogent problem hop with Cloudflare.",
)

# Healthy control path: Comcast peers directly with Google.
GOOGLE_PEER = HopTemplate(
    6,
    "68.86.85.1",
    "as15169-1.seattle.wa.seattle.comcast.net",
    base_rtt=14.8,
    jitter=1.5,
    loss=0.0,
    asn="AS7922",
    role="peering",
    city="Seattle, WA",
    layer=5,
    facility="Comcast → Google public peer",
    notes="Direct Google peering. Contrast with the Cogent path.",
)
GOOGLE_DEST = HopTemplate(
    7,
    "8.8.8.8",
    "dns.google",
    base_rtt=16.1,
    jitter=1.2,
    loss=0.0,
    asn="AS15169",
    role="dns",
    city="Anycast edge",
    layer=7,
)

LAN_DEVICES: tuple[LanDevice, ...] = (
    LanDevice("lan:you", "This host", "192.168.1.42", "host", "Apple", layer=0, notes="Trace source."),
    LanDevice("lan:gw", "U6 Gateway", "192.168.1.1", "gateway", "Ubiquiti", layer=1),
    LanDevice("lan:ap", "U6 Lite", "192.168.1.2", "ap", "Ubiquiti", layer=0),
    LanDevice("lan:nas", "Synology DS920+", "192.168.1.10", "device", "Synology", layer=0),
    LanDevice("lan:phone", "iPhone", "192.168.1.64", "device", "Apple", layer=0),
    LanDevice("lan:tv", "Apple TV", "192.168.1.80", "device", "Apple", layer=0),
)

CLOUDFLARE_HOPS: tuple[HopTemplate, ...] = (GW, ONT, RUR, AR, CR, COGENT_SEA, COGENT_SFO, COGENT_EDGE, CF_DEST)
GITHUB_HOPS: tuple[HopTemplate, ...] = (GW, ONT, RUR, AR, CR, COGENT_SEA, COGENT_SFO, GH_DEST)
GOOGLE_HOPS: tuple[HopTemplate, ...] = (GW, ONT, RUR, AR, CR, GOOGLE_PEER, GOOGLE_DEST)

PATHS: dict[str, tuple[HopTemplate, ...]] = {
    "1.1.1.1": CLOUDFLARE_HOPS,
    "one.one.one.one": CLOUDFLARE_HOPS,
    "cloudflare.com": CLOUDFLARE_HOPS,
    "8.8.8.8": GOOGLE_HOPS,
    "dns.google": GOOGLE_HOPS,
    "google.com": GOOGLE_HOPS,
    "github.com": GITHUB_HOPS,
    "140.82.112.3": GITHUB_HOPS,
}

DEFAULT_TARGET = "1.1.1.1"
BACKGROUND_TARGETS: tuple[str, ...] = ("1.1.1.1", "8.8.8.8", "github.com")


def resolve_path(target: str) -> tuple[str, tuple[HopTemplate, ...]]:
    key = target.strip().lower()
    if key in PATHS:
        canonical = {
            "one.one.one.one": "1.1.1.1",
            "cloudflare.com": "1.1.1.1",
            "dns.google": "8.8.8.8",
            "google.com": "8.8.8.8",
            "140.82.112.3": "github.com",
        }.get(key, key)
        return canonical, PATHS[key]
    # Unknown host: reuse the Cogent path and relabel the destination.
    dest = HopTemplate(
        9,
        None,
        target.strip() or "destination",
        base_rtt=97.0,
        jitter=12.0,
        loss=0.01,
        asn="AS174",
        role="anycast",
        city="Unknown edge",
        layer=7,
        notes="Synthetic demo destination behind the Cogent path.",
    )
    return target.strip() or DEFAULT_TARGET, CLOUDFLARE_HOPS[:-1] + (dest,)


def unique_templates(paths: dict[str, tuple[HopTemplate, ...]] | None = None) -> dict[str, HopTemplate]:
    table: dict[str, HopTemplate] = {}
    for hops in (paths or PATHS).values():
        for hop in hops:
            if hop.ip and hop.ip not in table:
                table[hop.ip] = hop
    return table


def sample_graph() -> dict[str, Any]:
    """Static sample topology used before the first live probe lands."""
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    seen: set[str] = set()

    for device in LAN_DEVICES:
        nodes.append(
            {
                "id": device.id,
                "label": device.name,
                "ip": device.ip,
                "kind": device.kind,
                "layer": device.layer,
                "vendor": device.vendor,
                "health": "ok",
                "hop": 0 if device.kind != "gateway" else 1,
                "rtt_ms": 0.4 if device.kind == "gateway" else 1.2,
                "added_ms": None,
                "loss_pct": 0.0,
                "asn": "PRIVATE",
                "provider": "Home network",
                "city": "LAN",
                "active": device.id in {"lan:you", "lan:gw"},
                "search": f"{device.name} {device.ip} {device.vendor} {device.kind} lan",
                "notes": device.notes,
            }
        )
        seen.add(device.id)
        if device.id != "lan:gw" and device.id != "lan:you":
            links.append({"source": "lan:gw", "target": device.id, "label": "LAN", "ms": 0.8, "health": "ok", "kind": "lan"})
    links.append({"source": "lan:you", "target": "lan:gw", "label": "0.5 ms", "ms": 0.5, "health": "ok", "kind": "lan"})

    for hops in (CLOUDFLARE_HOPS, GOOGLE_HOPS, GITHUB_HOPS):
        previous_id = "lan:you"
        previous_rtt = 0.0
        for hop in hops:
            if hop.node_id not in seen:
                extra = enrich_dict(hop.ip, hop.asn)
                health = "slow" if hop.problem else "ok"
                nodes.append(
                    {
                        "id": hop.node_id,
                        "label": _short_name(hop.hostname, hop.ip),
                        "hostname": hop.hostname,
                        "ip": hop.ip,
                        "kind": hop.role,
                        "layer": hop.layer,
                        "hop": hop.hop,
                        "rtt_ms": hop.base_rtt,
                        "added_ms": round(max(0.0, hop.base_rtt - previous_rtt), 2),
                        "loss_pct": round(hop.loss * 100.0, 1),
                        "health": health,
                        "asn": extra.get("asn"),
                        "provider": extra.get("provider"),
                        "as_name": extra.get("as_name"),
                        "city": hop.city,
                        "facility": hop.facility,
                        "problem": hop.problem,
                        "active": hop.ip in {item.ip for item in CLOUDFLARE_HOPS},
                        "search": _search_blob(hop, extra),
                        "notes": hop.notes,
                        "provider_detail": extra.get("provider_detail"),
                    }
                )
                seen.add(hop.node_id)
            added = max(0.0, hop.base_rtt - previous_rtt)
            health = "slow" if hop.problem else ("warn" if added >= 12 else "ok")
            label = f"+{added:.0f} ms" if added >= 1 else f"{hop.base_rtt:.1f} ms"
            links.append(
                {
                    "source": previous_id,
                    "target": hop.node_id,
                    "label": label,
                    "ms": round(added if added else hop.base_rtt, 2),
                    "health": health,
                    "kind": "wan",
                    "problem": hop.problem,
                }
            )
            previous_id = hop.node_id
            previous_rtt = hop.base_rtt

    return {"nodes": _dedupe_nodes(nodes), "links": _dedupe_links(links)}


def _short_name(hostname: str | None, ip: str | None) -> str:
    if hostname:
        head = hostname.split(".")[0]
        if len(head) > 22:
            return head[:20] + "…"
        return head
    return ip or "?"


def _search_blob(hop: HopTemplate, extra: dict[str, Any]) -> str:
    parts = [
        hop.hostname,
        hop.ip,
        hop.asn,
        extra.get("provider"),
        extra.get("as_name"),
        hop.city,
        hop.role,
        hop.facility,
        hop.notes,
        "problem" if hop.problem else "",
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        by_id[node["id"]] = node
    return list(by_id.values())


def _dedupe_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for link in links:
        key = (link["source"], link["target"])
        rev = (link["target"], link["source"])
        if key in seen or rev in seen:
            continue
        seen.add(key)
        unique.append(link)
    return unique
