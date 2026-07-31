"""WHOIS-style ownership lookups for traceroute hops via RDAP.

Uses the free `rdap.org <https://rdap.org>`_ bootstrap redirector
(``GET /ip/{address}``) — structured JSON, no API key. Private/reserved
addresses are skipped. Results are cached for the lifetime of the process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

from .geoip import is_private_ip

LOGGER = logging.getLogger(__name__)

RDAP_IP_URL = "https://rdap.org/ip/{ip}"


@dataclass
class WhoisInfo:
    """Normalized ownership / registration data for one IP."""

    ip: str
    handle: str | None = None
    name: str | None = None
    cidr: str | None = None
    start_address: str | None = None
    end_address: str | None = None
    country: str | None = None
    org: str | None = None
    registrant: str | None = None
    abuse_email: str | None = None
    abuse_phone: str | None = None
    asn: str | None = None
    type: str | None = None
    status: list[str] = field(default_factory=list)
    source: str = "rdap"
    found: bool = False
    is_private: bool = False
    error: str | None = None

    def summary(self) -> str:
        if self.is_private:
            return "Private / reserved address"
        if not self.found:
            return self.error or "No WHOIS record"
        parts = [p for p in (self.org or self.registrant, self.name, self.cidr) if p]
        return " · ".join(parts) if parts else (self.handle or "Registered network")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = self.summary()
        return payload


def _copy_whois(info: WhoisInfo) -> WhoisInfo:
    """Return an independent copy of a WhoisInfo (status list included)."""
    return WhoisInfo(
        ip=info.ip,
        handle=info.handle,
        name=info.name,
        cidr=info.cidr,
        start_address=info.start_address,
        end_address=info.end_address,
        country=info.country,
        org=info.org,
        registrant=info.registrant,
        abuse_email=info.abuse_email,
        abuse_phone=info.abuse_phone,
        asn=info.asn,
        type=info.type,
        status=list(info.status),
        source=info.source,
        found=info.found,
        is_private=info.is_private,
        error=info.error,
    )


def parse_rdap(ip: str, payload: dict[str, Any]) -> WhoisInfo:
    """Normalize an RDAP IP-network JSON object into :class:`WhoisInfo`."""
    cidr = None
    for cidr_entry in payload.get("cidr0_cidrs") or []:
        prefix = cidr_entry.get("v4prefix") or cidr_entry.get("v6prefix")
        length = cidr_entry.get("length")
        if prefix is not None and length is not None:
            cidr = f"{prefix}/{length}"
            break
    if cidr is None:
        start = payload.get("startAddress")
        end = payload.get("endAddress")
        if start and end and start == end:
            cidr = start
        elif start and end:
            cidr = f"{start} - {end}"

    org = None
    registrant = None
    abuse_email = None
    abuse_phone = None
    for entity in payload.get("entities") or []:
        roles = {str(role).lower() for role in (entity.get("roles") or [])}
        vcard = _vcard_fields(entity.get("vcardArray"))
        name = vcard.get("fn") or entity.get("handle")
        if "registrant" in roles and not registrant:
            registrant = name
        if "abuse" in roles:
            abuse_email = abuse_email or vcard.get("email")
            abuse_phone = abuse_phone or vcard.get("tel")
        if ("administrative" in roles or "technical" in roles) and not org:
            org = name
        if org is None and name:
            org = name

    asn = None
    for remark in payload.get("remarks") or []:
        for line in remark.get("description") or []:
            text = str(line)
            if "AS" in text and asn is None:
                # Prefer explicit ASN tokens when present in free-form remarks.
                for token in text.replace(",", " ").split():
                    if token.upper().startswith("AS") and token[2:].isdigit():
                        asn = token.upper()
                        break

    status = [str(item) for item in (payload.get("status") or [])]
    return WhoisInfo(
        ip=ip,
        handle=payload.get("handle"),
        name=payload.get("name"),
        cidr=cidr,
        start_address=payload.get("startAddress"),
        end_address=payload.get("endAddress"),
        country=payload.get("country"),
        org=org,
        registrant=registrant,
        abuse_email=abuse_email,
        abuse_phone=abuse_phone,
        asn=asn,
        type=payload.get("type"),
        status=status,
        found=True,
    )


def _vcard_fields(vcard_array: Any) -> dict[str, str]:
    """Extract common fields from an RDAP jCard ``vcardArray``."""
    result: dict[str, str] = {}
    if not isinstance(vcard_array, list) or len(vcard_array) < 2:
        return result
    entries = vcard_array[1]
    if not isinstance(entries, list):
        return result
    for entry in entries:
        if not isinstance(entry, list) or len(entry) < 4:
            continue
        key = str(entry[0]).lower()
        value = entry[3]
        if key == "fn" and isinstance(value, str):
            result["fn"] = value
        elif key == "email" and isinstance(value, str):
            result["email"] = value
        elif key == "tel":
            if isinstance(value, str):
                result["tel"] = value
            elif isinstance(value, dict) and "text" in value:
                result["tel"] = str(value["text"])
    return result


# Canned RDAP-style records used by demo mode (and tests).
DEMO_WHOIS: dict[str, WhoisInfo] = {
    "192.168.1.1": WhoisInfo(ip="192.168.1.1", is_private=True, found=False),
    "10.0.0.1": WhoisInfo(ip="10.0.0.1", is_private=True, found=False),
    "24.7.128.1": WhoisInfo(
        ip="24.7.128.1",
        handle="COMCAST-24-7-128-0",
        name="COMCAST-CABLE",
        cidr="24.7.128.0/17",
        country="US",
        org="Comcast Cable Communications, LLC",
        registrant="Comcast Cable Communications, LLC",
        abuse_email="abuse@comcast.net",
        asn="AS7922",
        type="ALLOCATED PA",
        found=True,
    ),
    "68.86.91.1": WhoisInfo(
        ip="68.86.91.1",
        handle="NET-68-86-0-0-1",
        name="COMCAST",
        cidr="68.86.0.0/15",
        country="US",
        org="Comcast Cable Communications, LLC",
        abuse_email="abuse@comcast.net",
        asn="AS7922",
        found=True,
    ),
    "96.110.40.1": WhoisInfo(
        ip="96.110.40.1",
        handle="NET-96-110-0-0-1",
        name="COMCAST",
        cidr="96.110.0.0/15",
        country="US",
        org="Comcast Cable Communications, LLC",
        asn="AS7922",
        found=True,
    ),
    "68.86.85.142": WhoisInfo(
        ip="68.86.85.142",
        handle="NET-68-86-0-0-1",
        name="COMCAST",
        cidr="68.86.0.0/15",
        country="US",
        org="Comcast Cable Communications, LLC",
        asn="AS7922",
        found=True,
    ),
    "4.69.140.94": WhoisInfo(
        ip="4.69.140.94",
        handle="LVLT-ORG-4-8",
        name="LVLT-ORG-4-8",
        cidr="4.0.0.0/9",
        country="US",
        org="Level 3 Parent, LLC",
        registrant="Level 3 Parent, LLC",
        abuse_email="abuse@level3.com",
        asn="AS3356",
        found=True,
    ),
    "4.69.219.94": WhoisInfo(
        ip="4.69.219.94",
        handle="LVLT-ORG-4-8",
        name="LVLT-ORG-4-8",
        cidr="4.0.0.0/9",
        country="US",
        org="Level 3 Parent, LLC",
        asn="AS3356",
        found=True,
    ),
    "4.15.180.50": WhoisInfo(
        ip="4.15.180.50",
        handle="LVLT-ORG-4-8",
        name="LVLT-ORG-4-8",
        cidr="4.0.0.0/9",
        country="US",
        org="Level 3 Parent, LLC",
        asn="AS3356",
        found=True,
    ),
    "104.16.248.249": WhoisInfo(
        ip="104.16.248.249",
        handle="CLOUDFLARENET",
        name="CLOUDFLARENET",
        cidr="104.16.0.0/13",
        country="US",
        org="Cloudflare, Inc.",
        registrant="Cloudflare, Inc.",
        abuse_email="abuse@cloudflare.com",
        asn="AS13335",
        found=True,
    ),
    "142.250.72.14": WhoisInfo(
        ip="142.250.72.14",
        handle="GOGL",
        name="GOOGLE",
        cidr="142.250.0.0/15",
        country="US",
        org="Google LLC",
        registrant="Google LLC",
        abuse_email="network-abuse@google.com",
        asn="AS15169",
        found=True,
    ),
    "151.101.1.67": WhoisInfo(
        ip="151.101.1.67",
        handle="SKYCA-3",
        name="SKYCA-3",
        cidr="151.101.0.0/16",
        country="US",
        org="Fastly, Inc.",
        registrant="Fastly, Inc.",
        abuse_email="abuse@fastly.com",
        asn="AS54113",
        found=True,
    ),
    "8.8.8.8": WhoisInfo(
        ip="8.8.8.8",
        handle="GOGL",
        name="LVLT-GOGL-8-8-8",
        cidr="8.8.8.0/24",
        country="US",
        org="Google LLC",
        registrant="Google LLC",
        abuse_email="network-abuse@google.com",
        asn="AS15169",
        found=True,
    ),
    "1.1.1.1": WhoisInfo(
        ip="1.1.1.1",
        handle="APNIC-LABS",
        name="APNIC-LABS",
        cidr="1.1.1.0/24",
        country="AU",
        org="Cloudflare, Inc.",
        registrant="APNIC Pty Ltd",
        abuse_email="abuse@apnic.net",
        asn="AS13335",
        found=True,
    ),
}


class WhoisResolver:
    """Cached RDAP/WHOIS lookups."""

    def __init__(self, *, request_timeout: float = 12.0, demo: bool = False) -> None:
        self.request_timeout = request_timeout
        self.demo = demo
        self._cache: dict[str, WhoisInfo] = {}

    async def lookup_many(self, ips: list[str]) -> dict[str, WhoisInfo]:
        results: dict[str, WhoisInfo] = {}
        pending: list[str] = []
        for ip in dict.fromkeys(ips):
            if is_private_ip(ip):
                info = WhoisInfo(ip=ip, is_private=True, found=False)
                results[ip] = info
                self._cache[ip] = info
                continue
            cached = self._cache.get(ip)
            if cached is not None:
                results[ip] = cached
            else:
                pending.append(ip)

        if self.demo:
            for ip in pending:
                info = _copy_whois(DEMO_WHOIS.get(ip) or WhoisInfo(
                    ip=ip,
                    found=False,
                    error="No demo WHOIS record for this address",
                ))
                self._cache[ip] = info
                results[ip] = info
            return results

        # Bound concurrency so we don't hammer rdap.org when a route has many hops.
        semaphore = asyncio.Semaphore(4)

        async def _one(ip: str) -> None:
            async with semaphore:
                info = await self.lookup(ip)
                results[ip] = info

        await asyncio.gather(*[_one(ip) for ip in pending])
        return results

    async def lookup(self, ip: str) -> WhoisInfo:
        if is_private_ip(ip):
            info = WhoisInfo(ip=ip, is_private=True, found=False)
            self._cache[ip] = info
            return info
        cached = self._cache.get(ip)
        if cached is not None:
            return cached
        if self.demo:
            canned = DEMO_WHOIS.get(ip)
            info = canned or WhoisInfo(ip=ip, found=False, error="No demo WHOIS record")
            self._cache[ip] = info
            return info
        try:
            payload = await asyncio.to_thread(self._fetch_rdap, ip)
            info = parse_rdap(ip, payload)
        except urllib.error.HTTPError as exc:
            info = WhoisInfo(ip=ip, found=False, error=f"RDAP HTTP {exc.code}")
            LOGGER.info("RDAP miss for %s: HTTP %s", ip, exc.code)
        except Exception as exc:
            info = WhoisInfo(ip=ip, found=False, error=str(exc))
            LOGGER.warning("RDAP lookup failed for %s: %s", ip, exc)
        self._cache[ip] = info
        return info

    def _fetch_rdap(self, ip: str) -> dict[str, Any]:
        request = urllib.request.Request(
            RDAP_IP_URL.format(ip=ip),
            headers={"User-Agent": "trace-radar/0.1", "Accept": "application/rdap+json, application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))
