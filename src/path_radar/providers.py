"""ASN / operator catalog for problem-router inspection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Provider:
    asn: str
    name: str
    aka: str | None = None
    rir: str | None = None
    prefix: str | None = None
    website: str | None = None
    looking_glass: str | None = None
    noc: str | None = None
    notes: str | None = None
    typical_issues: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "asn": self.asn,
            "name": self.name,
            "aka": self.aka,
            "rir": self.rir,
            "prefix": self.prefix,
            "website": self.website,
            "looking_glass": self.looking_glass,
            "noc": self.noc,
            "notes": self.notes,
            "typical_issues": list(self.typical_issues),
        }


PROVIDERS: dict[str, Provider] = {
    "PRIVATE": Provider(
        asn="PRIVATE",
        name="RFC1918 / customer LAN",
        aka="Home network",
        rir=None,
        prefix="192.168.0.0/16",
        notes="CPE and LAN hosts. Delay here is almost always Wi-Fi, a slow gateway, or a double-NAT.",
    ),
    "CGNAT": Provider(
        asn="CGNAT",
        name="Carrier-grade NAT",
        aka="ISP last-mile",
        prefix="10.0.0.0/8",
        notes="ISP-facing ONT or CGNAT. Low single-digit milliseconds is healthy.",
    ),
    "AS7922": Provider(
        asn="AS7922",
        name="Comcast Cable Communications, LLC",
        aka="Xfinity",
        rir="ARIN",
        prefix="96.120.0.0/16",
        website="https://www.xfinity.com",
        looking_glass="https://lookingglass.comcast.com/",
        noc="noc@comcast.com",
        notes=(
            "Residential last-mile and metro aggregation. Delay that appears on Comcast hops "
            "and then stays flat is often Wi-Fi or the CMTS. Delay that jumps at the next ASN "
            "is usually a peering handoff, not the Comcast router itself."
        ),
        typical_issues=(
            "CMTS congestion on a node",
            "Wi-Fi mistaken for WAN latency",
            "Peering handoff to a transit network",
        ),
    ),
    "AS174": Provider(
        asn="AS174",
        name="Cogent Communications",
        aka="Cogent",
        rir="ARIN",
        prefix="154.54.0.0/16",
        website="https://www.cogentco.com",
        looking_glass="https://www.cogentco.com/en/network/looking-glass",
        noc="noc@cogentco.com",
        notes=(
            "Cogent's settlement-free peering with residential ISPs is frequently saturated "
            "(the so-called Cogent tax). Latency and loss typically appear at the first Cogent "
            "hop after the ISP handoff — not on Cogent long-haul, and not at the destination. "
            "Destinations that peer directly with the access ISP (for example Google) stay fast "
            "while anything behind Cogent (Cloudflare, GitHub, many CDNs) turns red together."
        ),
        typical_issues=(
            "Peering congestion with residential ISPs, worse on weekday evenings",
            "Asymmetric return path",
            "ICMP rate-limiting that looks like loss but isn't forwarding loss",
        ),
    ),
    "AS13335": Provider(
        asn="AS13335",
        name="Cloudflare, Inc.",
        aka="Cloudflare",
        rir="ARIN",
        prefix="1.1.1.0/24",
        website="https://www.cloudflare.com",
        looking_glass="https://www.cloudflare.com/network/",
        notes="Anycast DNS / edge. If this hop is slow only when the previous ASN is slow, the destination is fine.",
    ),
    "AS15169": Provider(
        asn="AS15169",
        name="Google LLC",
        aka="Google",
        rir="ARIN",
        prefix="8.8.8.0/24",
        website="https://developers.google.com/speed/public-dns",
        notes="Direct peering with large access ISPs is common, so 8.8.8.8 is a useful healthy-path control.",
    ),
    "AS36459": Provider(
        asn="AS36459",
        name="GitHub, Inc.",
        aka="GitHub",
        rir="ARIN",
        prefix="140.82.112.0/20",
        website="https://github.com",
        notes="Often reached via transit (Cogent, NTT, Level 3) rather than a direct Comcast peer.",
    ),
    "AS3356": Provider(
        asn="AS3356",
        name="Level 3 Parent, LLC",
        aka="Lumen / Level 3",
        rir="ARIN",
        notes="Global transit. Jumps here are usually a previous-hop handoff or a congested metro.",
    ),
    "AS6939": Provider(
        asn="AS6939",
        name="Hurricane Electric LLC",
        aka="HE.net",
        rir="ARIN",
        looking_glass="https://lg.he.net/",
        notes="IPv6-heavy transit. Useful looking-glass when diagnosing HE hops.",
    ),
}

IP_TO_ASN: dict[str, str] = {
    "192.168.1.1": "PRIVATE",
    "192.168.1.2": "PRIVATE",
    "192.168.1.10": "PRIVATE",
    "192.168.1.42": "PRIVATE",
    "192.168.1.64": "PRIVATE",
    "192.168.1.80": "PRIVATE",
    "10.4.0.1": "CGNAT",
    "96.120.88.141": "AS7922",
    "68.87.194.37": "AS7922",
    "68.86.90.5": "AS7922",
    "68.86.85.1": "AS7922",
    "154.54.30.17": "AS174",
    "154.54.31.74": "AS174",
    "154.54.42.90": "AS174",
    "1.1.1.1": "AS13335",
    "8.8.8.8": "AS15169",
    "140.82.112.3": "AS36459",
}


def provider_for_asn(asn: str | None) -> Provider | None:
    if not asn:
        return None
    return PROVIDERS.get(asn.upper()) if asn.upper() in PROVIDERS else PROVIDERS.get(asn)


def provider_for_ip(ip: str | None) -> Provider | None:
    if not ip:
        return None
    asn = IP_TO_ASN.get(ip)
    if asn:
        return PROVIDERS.get(asn)
    if ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("172."):
        return PROVIDERS["PRIVATE"]
    return None


def enrich_dict(ip: str | None, asn: str | None = None) -> dict[str, Any]:
    provider = provider_for_asn(asn) if asn else None
    if provider is None:
        provider = provider_for_ip(ip)
    if provider is None:
        return {
            "asn": asn,
            "provider": None,
            "provider_detail": None,
        }
    return {
        "asn": provider.asn,
        "provider": provider.aka or provider.name,
        "as_name": provider.name,
        "provider_detail": provider.as_dict(),
    }
