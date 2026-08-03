"""IP geolocation for traceroute hops.

Live lookups use the free `ip-api.com <http://ip-api.com>`_ JSON API (batch
endpoint, no key required). Private/reserved addresses are detected locally
with :mod:`ipaddress` and never sent over the network. Results are cached in
memory for the lifetime of the process.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)

BATCH_URL = "http://ip-api.com/batch"
SELF_URL = "http://ip-api.com/json/"
FIELDS = "status,query,lat,lon,city,country,countryCode,isp,org,as"
BATCH_LIMIT = 100


@dataclass
class GeoInfo:
    """Location and network-owner metadata for one IP address."""

    ip: str
    lat: float | None = None
    lon: float | None = None
    city: str | None = None
    country: str | None = None
    country_code: str | None = None
    isp: str | None = None
    org: str | None = None
    asn: str | None = None
    is_private: bool = False

    @property
    def located(self) -> bool:
        return self.lat is not None and self.lon is not None

    def place_label(self) -> str:
        if self.is_private:
            return "Private network"
        if self.city and self.country:
            return f"{self.city}, {self.country}"
        if self.country:
            return self.country
        return "Unknown location"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["place"] = self.place_label()
        return payload


def is_private_ip(ip: str) -> bool:
    """True for RFC1918/loopback/link-local/CGNAT/reserved addresses."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _parse_entry(entry: dict[str, Any]) -> GeoInfo | None:
    ip = str(entry.get("query") or "")
    if not ip or entry.get("status") != "success":
        return None
    return GeoInfo(
        ip=ip,
        lat=entry.get("lat"),
        lon=entry.get("lon"),
        city=entry.get("city") or None,
        country=entry.get("country") or None,
        country_code=entry.get("countryCode") or None,
        isp=entry.get("isp") or None,
        org=entry.get("org") or None,
        asn=entry.get("as") or None,
    )


class GeoResolver:
    """Cached geolocation lookups against ip-api.com."""

    def __init__(self, *, request_timeout: float = 15.0) -> None:
        self.request_timeout = request_timeout
        self._cache: dict[str, GeoInfo] = {}

    async def lookup_many(self, ips: list[str]) -> dict[str, GeoInfo]:
        results: dict[str, GeoInfo] = {}
        pending: list[str] = []
        for ip in dict.fromkeys(ips):
            if is_private_ip(ip):
                results[ip] = GeoInfo(ip=ip, is_private=True)
                continue
            cached = self._cache.get(ip)
            if cached is not None:
                results[ip] = cached
            else:
                pending.append(ip)
        for start in range(0, len(pending), BATCH_LIMIT):
            chunk = pending[start : start + BATCH_LIMIT]
            try:
                entries = await asyncio.to_thread(self._fetch_batch, chunk)
            except Exception as exc:
                LOGGER.warning("GeoIP batch lookup failed (%s); leaving %d hops unlocated", exc, len(chunk))
                entries = []
            for entry in entries:
                info = _parse_entry(entry)
                if info is not None:
                    self._cache[info.ip] = info
                    results[info.ip] = info
        for ip in pending:
            results.setdefault(ip, GeoInfo(ip=ip))
        return results

    async def lookup_self(self) -> GeoInfo | None:
        """Geolocate this machine's public IP (the origin of every trace)."""
        try:
            entry = await asyncio.to_thread(self._fetch_self)
        except Exception as exc:
            LOGGER.warning("GeoIP self lookup failed: %s", exc)
            return None
        return _parse_entry(entry)

    def _fetch_batch(self, ips: list[str]) -> list[dict[str, Any]]:
        body = json.dumps([{"query": ip, "fields": FIELDS} for ip in ips]).encode("utf-8")
        request = urllib.request.Request(
            BATCH_URL,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "trace-radar/0.1"},
        )
        with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _fetch_self(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{SELF_URL}?fields={FIELDS}",
            headers={"User-Agent": "trace-radar/0.1"},
        )
        with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))
