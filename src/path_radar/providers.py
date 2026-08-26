"""ASN / operator catalog plus live Team Cymru / RIPE lookups."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from ipaddress import ip_address
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
    "AS16509": Provider(
        asn="AS16509",
        name="Amazon.com, Inc.",
        aka="Amazon",
        rir="ARIN",
        notes="AWS / Amazon edge. Seeing this hop usually means you have reached a cloud on-ramp, not a fault on your LAN.",
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


def ip_kind(ip: str | None) -> str:
    if not ip:
        return "unknown"
    try:
        parsed = ip_address(ip)
    except ValueError:
        return "unknown"
    packed = int(parsed)
    if packed >= 0xF0000000:
        return "reserved"
    if parsed.is_loopback:
        return "loopback"
    if parsed.is_link_local:
        return "link-local"
    if parsed.is_multicast:
        return "reserved"
    if parsed.is_private:
        return "private"
    if 0x64400000 <= packed <= 0x647FFFFF:
        return "cgnat"
    return "public"


def reversed_ipv4(ip: str) -> str:
    return ".".join(reversed(ip.split(".")))


def parse_cymru_origin(txt: str) -> dict[str, str] | None:
    cleaned = txt.strip().strip('"')
    parts = [part.strip() for part in cleaned.split("|")]
    if len(parts) < 4:
        return None
    asn = re.sub(r"[^0-9]", "", parts[0])
    if not asn:
        return None
    return {
        "asn": asn,
        "prefix": parts[1],
        "cc": parts[2],
        "rir": parts[3],
        "date": parts[4] if len(parts) > 4 else "",
    }


def parse_cymru_asn(txt: str) -> dict[str, str] | None:
    cleaned = txt.strip().strip('"')
    parts = [part.strip() for part in cleaned.split("|")]
    if len(parts) < 5:
        return None
    return {
        "asn": re.sub(r"[^0-9]", "", parts[0]),
        "cc": parts[1],
        "rir": parts[2],
        "date": parts[3],
        "name": parts[4],
    }


def _dns_txt(qname: str, timeout: float = 1.2) -> str | None:
    dig = shutil.which("dig")
    if dig:
        try:
            completed = subprocess.run(
                [dig, "+short", "+time=1", "+tries=1", qname, "TXT"],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout + 0.5,
            )
            text = (completed.stdout or "").strip()
            if text:
                return text.splitlines()[0]
        except (OSError, subprocess.TimeoutExpired):
            pass
    url = "https://dns.google/resolve?" + urllib.parse.urlencode({"name": qname, "type": "TXT"})
    payload = _http_json(url, timeout=timeout)
    if not payload:
        return None
    for answer in payload.get("Answer") or []:
        data = str(answer.get("data") or "").strip()
        if data:
            return data
    return None


def _http_json(url: str, timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "path-radar/0.1"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def cymru_origin(ip: str) -> dict[str, str] | None:
    qname = f"{reversed_ipv4(ip)}.origin.asn.cymru.com"
    txt = _dns_txt(qname)
    if not txt:
        return None
    return parse_cymru_origin(txt)


def cymru_asn_name(asn: str) -> dict[str, str] | None:
    qname = f"AS{asn}.asn.cymru.com"
    txt = _dns_txt(qname)
    if not txt:
        return None
    return parse_cymru_asn(txt)


def ripe_geoloc(ip: str) -> dict[str, str] | None:
    url = "https://stat.ripe.net/data/geoloc/data.json?resource=" + urllib.parse.quote(ip)
    payload = _http_json(url, timeout=2.0)
    if not payload or payload.get("status") != "ok":
        return None
    resources = ((payload.get("data") or {}).get("located_resources")) or []
    for resource in resources:
        for location in resource.get("locations") or []:
            city = (location.get("city") or "").strip()
            country = (location.get("country") or "").strip()
            if country == "?":
                country = ""
            if city or country:
                return {"city": city or None, "country": country or None}
    return None


_LOOKUP_CACHE: dict[str, dict[str, Any]] = {}


def lookup_ip(ip: str | None) -> dict[str, Any]:
    """Live (cached) ASN + provider + geo for a hop IP."""
    if not ip:
        return {"asn": None, "provider": None, "provider_detail": None}
    cached = _LOOKUP_CACHE.get(ip)
    if cached is not None:
        return cached
    result = _lookup_ip_uncached(ip)
    _LOOKUP_CACHE[ip] = result
    return result


def _lookup_ip_uncached(ip: str) -> dict[str, Any]:
    kind = ip_kind(ip)
    if kind in {"private", "loopback", "link-local"}:
        extra = enrich_dict(ip, "PRIVATE")
        extra["city"] = "LAN"
        extra["role"] = "gateway" if ip.endswith(".1") else "lan"
        return extra
    if kind == "cgnat":
        extra = enrich_dict(ip, "CGNAT")
        extra["role"] = "access"
        return extra
    if kind == "reserved":
        provider = Provider(
            asn="RESERVED",
            name="Non-routable overlay hop",
            aka="Fabric",
            notes=(
                "This hop answered from a reserved address (often a cloud underlay, "
                "hypervisor fabric, or carrier encapsulation). Public ASN registries "
                "do not publish an operator for it."
            ),
        )
        return {
            "asn": "RESERVED",
            "provider": provider.aka,
            "as_name": provider.name,
            "city": None,
            "country": None,
            "role": "overlay",
            "notes": provider.notes,
            "provider_detail": provider.as_dict(),
        }
    if kind != "public":
        return {"asn": None, "provider": None, "provider_detail": None}

    origin = cymru_origin(ip)
    asn_num = origin["asn"] if origin else None
    asn = f"AS{asn_num}" if asn_num else None
    named = cymru_asn_name(asn_num) if asn_num else None
    geo = ripe_geoloc(ip)
    catalog = provider_for_asn(asn) if asn else None
    as_name = (catalog.name if catalog else None) or (named["name"] if named else None)
    provider_label = (catalog.aka if catalog else None) or as_name
    city = None
    country = (origin or {}).get("cc") or None
    if geo:
        city = geo.get("city") or city
        country = geo.get("country") or country
    if catalog:
        detail = catalog.as_dict()
    else:
        detail = Provider(
            asn=asn or "UNKNOWN",
            name=as_name or "Unknown operator",
            rir=(origin or {}).get("rir"),
            prefix=(origin or {}).get("prefix"),
            notes="Live Team Cymru / RIPE record. No local handbook entry for this ASN.",
        ).as_dict()
    if origin:
        detail["prefix"] = origin.get("prefix") or detail.get("prefix")
        detail["rir"] = origin.get("rir") or detail.get("rir")
    detail["country"] = country
    if city:
        detail["city"] = city
    return {
        "asn": asn,
        "provider": provider_label,
        "as_name": as_name,
        "city": city or country,
        "country": country,
        "prefix": (origin or {}).get("prefix"),
        "role": "anycast" if catalog and catalog.asn in {"AS13335", "AS15169"} else "transit",
        "notes": catalog.notes if catalog else None,
        "provider_detail": detail,
    }
