"""ADS-B feed backends for SkyVeil.

The live backend polls the free `adsb.lol <https://api.adsb.lol>`_ public
aggregator:

- ``/v2/point/<lat>/<lon>/<radius_nm>`` for the regional traffic pool the
  kinematic anomaly checks run against
- ``/v2/pia``, ``/v2/ladd``, ``/v2/mil``, and ``/v2/squawk/7500,7600,7700``
  — global "flagged" feeds merged in regardless of region, since a privacy
  address, an opted-out LADD flight, or a declared emergency anywhere is
  worth surfacing even outside the watched radius.

The demo backend simulates one flight per anomaly category so the dashboard
and detections feed are populatable without network access.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from .state import FlightObservation, SkyState

LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.adsb.lol/v2"
DEFAULT_CENTER = (39.8283, -98.5795)  # geographic center of the continental US
DEFAULT_RADIUS_NM = 250.0
EMERGENCY_SQUAWK_LIST = "7500,7600,7700"


class ScannerBackend(Protocol):
    async def run(self) -> None:
        """Run the scanner until cancelled."""


@dataclass
class AdsbLolBackend:
    """Live poller combining a regional traffic pool with global flagged feeds."""

    state: SkyState
    interval: float = 20.0
    center: tuple[float, float] = DEFAULT_CENTER
    radius_nm: float = DEFAULT_RADIUS_NM
    request_timeout: float = 20.0

    async def run(self) -> None:
        first = await self._poll_once()
        LOGGER.info("Live ADS-B poll returned %d aircraft", len(first))
        await self.state.ingest_cycle(first)
        while True:
            await asyncio.sleep(self.interval)
            try:
                observations = await self._poll_once()
            except Exception as exc:
                LOGGER.warning("ADS-B poll failed (%s); keeping previous cycle", exc)
                await self.state.add_system_event("poll-error", f"ADS-B poll failed: {exc}")
                continue
            await self.state.ingest_cycle(observations)

    async def _poll_once(self) -> list[FlightObservation]:
        lat, lon = self.center
        regional_url = f"{API_BASE}/point/{lat}/{lon}/{self.radius_nm}"
        payloads = await asyncio.gather(
            asyncio.to_thread(self._fetch_json, regional_url),
            asyncio.to_thread(self._fetch_json, f"{API_BASE}/pia"),
            asyncio.to_thread(self._fetch_json, f"{API_BASE}/ladd"),
            asyncio.to_thread(self._fetch_json, f"{API_BASE}/mil"),
            asyncio.to_thread(self._fetch_json, f"{API_BASE}/squawk/{EMERGENCY_SQUAWK_LIST}"),
            return_exceptions=True,
        )
        regional, pia, ladd, mil, emergency = payloads
        pia_hexes = _hex_set(pia)
        ladd_hexes = _hex_set(ladd)
        mil_hexes = _hex_set(mil)

        merged: dict[str, dict[str, Any]] = {}
        for payload in (regional, emergency, pia, ladd, mil):
            if isinstance(payload, BaseException):
                continue
            for entry in payload.get("ac") or []:
                hex_id = str(entry.get("hex", "")).lower()
                if hex_id:
                    merged.setdefault(hex_id, entry)

        now = datetime.now(UTC)
        return [
            parse_aircraft(
                entry,
                now,
                is_pia=hex_id in pia_hexes,
                is_ladd=hex_id in ladd_hexes,
                is_mil=hex_id in mil_hexes,
            )
            for hex_id, entry in merged.items()
        ]

    def _fetch_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": "skyveil/0.1"})
        with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def _hex_set(payload: Any) -> set[str]:
    if isinstance(payload, BaseException):
        return set()
    return {str(entry.get("hex", "")).lower() for entry in payload.get("ac") or []}


def parse_aircraft(
    entry: dict[str, Any],
    now: datetime,
    *,
    is_pia: bool = False,
    is_ladd: bool = False,
    is_mil: bool = False,
) -> FlightObservation:
    alt = entry.get("alt_baro")
    on_ground = alt == "ground"
    altitude = int(alt) if isinstance(alt, (int, float)) else None
    emergency = entry.get("emergency")
    return FlightObservation(
        hex_id=str(entry.get("hex", "")).lower(),
        callsign=(entry.get("flight") or "").strip() or None,
        registration=entry.get("r"),
        type_code=entry.get("t"),
        emitter_category=entry.get("category"),
        lat=entry.get("lat"),
        lon=entry.get("lon"),
        altitude_ft=altitude,
        ground_speed_kt=entry.get("gs"),
        track_deg=entry.get("track"),
        baro_rate_fpm=entry.get("baro_rate") if isinstance(entry.get("baro_rate"), (int, float)) else entry.get("geom_rate"),
        squawk=entry.get("squawk"),
        emergency_field=str(emergency) if emergency else None,
        nic=entry.get("nic"),
        nac_p=entry.get("nac_p"),
        on_ground=on_ground,
        is_pia=is_pia,
        is_ladd=is_ladd,
        is_mil=is_mil,
        observed_at=now,
    )


# --- Demo backend -----------------------------------------------------------
#
# One simulated flight per anomaly category, plus a handful of routine
# background traffic, so every part of the dashboard has something to show
# without live network access.


@dataclass
class _SimFlight:
    hex_id: str
    callsign: str | None
    registration: str | None
    type_code: str | None
    category: str | None
    lat: float
    lon: float
    altitude_ft: int
    heading: float
    ground_speed_kt: float
    squawk: str = "1200"
    emergency_field: str | None = None
    baro_rate_fpm: float = 0.0
    is_pia: bool = False
    is_ladd: bool = False
    is_mil: bool = False
    on_ground: bool = False
    nic: int = 8


def _routine_fleet() -> list[_SimFlight]:
    seed = [
        ("dm0001", "UAL118", "N118UA", "B738", "A3", 39.9, -104.7, 34000, 90, 460),
        ("dm0002", "DAL42", "N42DL", "A321", "A3", 41.8, -87.6, 36000, 210, 470),
        ("dm0003", "SWA221", "N221WN", "B737", "A3", 32.9, -97.0, 31000, 45, 440),
        ("dm0004", "N4412C", "N4412C", "C172", "A1", 34.0, -118.3, 3500, 300, 110),
        ("dm0005", "AAL77", "N977AN", "B772", "A5", 40.6, -74.0, 38000, 250, 500),
    ]
    return [
        _SimFlight(hex_id=h, callsign=c, registration=r, type_code=t, category=cat, lat=lat, lon=lon,
                   altitude_ft=alt, heading=hdg, ground_speed_kt=gs)
        for h, c, r, t, cat, lat, lon, alt, hdg, gs in seed
    ]


@dataclass
class DemoScannerBackend:
    """Simulated traffic covering every anomaly category on a short loop."""

    state: SkyState
    interval: float = 2.0
    incident_at: int = 8

    def __post_init__(self) -> None:
        random.seed(20260830)
        self._fleet: list[_SimFlight] = _routine_fleet()
        self._incidents_spawned = False

    async def run(self) -> None:
        LOGGER.info("Starting SkyVeil demo simulator (incidents begin at tick %d)", self.incident_at)
        tick = 0
        while True:
            tick += 1
            self._advance(tick)
            observations = [self._observe(flight) for flight in self._fleet]
            await self.state.ingest_cycle(observations)
            await asyncio.sleep(self.interval)

    def _advance(self, tick: int) -> None:
        for flight in self._fleet:
            if flight.on_ground:
                continue
            speed_deg = flight.ground_speed_kt / 3600.0 / 52.0
            flight.lat += math.cos(math.radians(flight.heading)) * speed_deg
            flight.lon += math.sin(math.radians(flight.heading)) * speed_deg

        if tick == self.incident_at and not self._incidents_spawned:
            self._incidents_spawned = True
            self._spawn_incidents()

        if tick > self.incident_at:
            for flight in self._fleet:
                if flight.hex_id == "inc-erratic":
                    flight.heading = (flight.heading + random.uniform(40, 80)) % 360
                    flight.baro_rate_fpm = random.choice([-7200.0, 6800.0, -6500.0])
                if flight.hex_id == "inc-test":
                    flight.heading = (flight.heading + 70) % 360

    def _spawn_incidents(self) -> None:
        host = self._fleet[0]
        self._fleet.append(
            _SimFlight(
                hex_id="inc-emerg",
                callsign="DAL42",
                registration="N42DL",
                type_code="A321",
                category="A3",
                lat=self._fleet[1].lat,
                lon=self._fleet[1].lon,
                altitude_ft=self._fleet[1].altitude_ft,
                heading=self._fleet[1].heading,
                ground_speed_kt=430,
                squawk="7700",
                emergency_field="general",
            )
        )
        self._fleet.append(
            _SimFlight(
                hex_id="inc-cloak",
                callsign=None,
                registration=None,
                type_code=None,
                category="A0",
                lat=38.9,
                lon=-77.0,
                altitude_ft=21000,
                heading=180,
                ground_speed_kt=380,
                squawk="0413",
                is_pia=True,
                nic=0,
            )
        )
        self._fleet.append(
            _SimFlight(
                hex_id="inc-test",
                callsign="XPRMT12",
                registration="N912TX",
                type_code=None,
                category="B7",
                lat=34.9054,
                lon=-117.8837,
                altitude_ft=52000,
                heading=0,
                ground_speed_kt=210,
            )
        )
        self._fleet.append(
            _SimFlight(
                hex_id="inc-erratic",
                callsign="N7788Q",
                registration="N7788Q",
                type_code="C172",
                category="A1",
                lat=host.lat + 1.5,
                lon=host.lon + 1.5,
                altitude_ft=8000,
                heading=90,
                ground_speed_kt=310,
            )
        )

    def _observe(self, flight: _SimFlight) -> FlightObservation:
        return FlightObservation(
            hex_id=flight.hex_id,
            callsign=flight.callsign,
            registration=flight.registration,
            type_code=flight.type_code,
            emitter_category=flight.category,
            lat=round(flight.lat, 5),
            lon=round(flight.lon, 5),
            altitude_ft=None if flight.on_ground else flight.altitude_ft,
            ground_speed_kt=flight.ground_speed_kt,
            track_deg=round(flight.heading, 1),
            baro_rate_fpm=flight.baro_rate_fpm,
            squawk=flight.squawk,
            emergency_field=flight.emergency_field,
            nic=flight.nic,
            nac_p=8,
            on_ground=flight.on_ground,
            is_pia=flight.is_pia,
            is_ladd=flight.is_ladd,
            is_mil=flight.is_mil,
            observed_at=datetime.now(UTC),
        )
