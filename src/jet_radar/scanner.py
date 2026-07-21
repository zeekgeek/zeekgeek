"""ADS-B feed backends for the private-jet radar.

The live backend polls the free `adsb.lol <https://api.adsb.lol>`_ REST API
(``/v2/type/<codes>``) for business jets and aerial-refueling tankers. Optional
``--center`` / ``--radius-nm`` narrow the watch to a region.

The demo backend simulates:
1. A calm baseline of routine bizjet traffic
2. Watched "reactive" jets (Musk/Gates-style) sitting still, then scrambling
3. Privacy-heavy jets (Bezos/Zuckerberg-style) going quiet near Hawaii
4. A tanker rendezvous and a high-speed maneuver during the surge

Enough correlated triggers fire the strange-event alarm.
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

from .state import JetObservation, RadarState
from .watchlist import TANKER_TYPES

LOGGER = logging.getLogger(__name__)

BIZJET_TYPES = [
    "GLF4", "GLF5", "GLF6", "GA5C", "GA6C", "G150", "G280",
    "GL5T", "GL7T", "GLEX", "CL30", "CL35", "CL60", "LJ35", "LJ45", "LJ60", "LJ75",
    "C25A", "C25B", "C25C", "C500", "C510", "C525", "C550", "C560", "C56X", "C680", "C68A", "C700", "C750",
    "F2TH", "F900", "FA10", "FA20", "FA50", "FA7X", "FA8X",
    "E35L", "E545", "E550", "E55P", "H25B", "HDJT", "PC24", "PRM1",
]

API_BASE = "https://api.adsb.lol/v2"
TYPES_PER_REQUEST = 15


class ScannerBackend(Protocol):
    async def run(self) -> None:
        """Run the scanner until cancelled."""


@dataclass
class AdsbLolBackend:
    """Live poller for the adsb.lol public ADS-B aggregator."""

    state: RadarState
    interval: float = 60.0
    types: list[str] = field(default_factory=lambda: list(BIZJET_TYPES))
    include_tankers: bool = True
    center: tuple[float, float] | None = None
    radius_nm: float = 250.0
    request_timeout: float = 30.0

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

    async def _poll_once(self) -> list[JetObservation]:
        type_list = list(self.types)
        if self.include_tankers:
            type_list = type_list + [t for t in TANKER_TYPES if t not in type_list]
        aircraft: list[dict[str, Any]] = []
        for start in range(0, len(type_list), TYPES_PER_REQUEST):
            chunk = type_list[start : start + TYPES_PER_REQUEST]
            url = f"{API_BASE}/type/{','.join(chunk)}"
            payload = await asyncio.to_thread(self._fetch_json, url)
            aircraft.extend(payload.get("ac") or [])
        now = datetime.now(UTC)
        tanker_set = set(TANKER_TYPES)
        observations = [
            parse_aircraft(entry, now, is_tanker=str(entry.get("t") or "") in tanker_set)
            for entry in aircraft
        ]
        if self.center is not None:
            lat, lon = self.center
            from .watchlist import haversine_nm

            observations = [
                obs
                for obs in observations
                if obs.lat is not None
                and obs.lon is not None
                and haversine_nm(lat, lon, obs.lat, obs.lon) <= self.radius_nm
            ]
        return observations

    def _fetch_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": "jet-radar/0.1"})
        with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def parse_aircraft(entry: dict[str, Any], now: datetime, *, is_tanker: bool = False) -> JetObservation:
    alt = entry.get("alt_baro")
    on_ground = alt == "ground"
    altitude = int(alt) if isinstance(alt, (int, float)) else None
    return JetObservation(
        hex_id=str(entry.get("hex", "")).lower(),
        callsign=(entry.get("flight") or "").strip() or None,
        registration=entry.get("r"),
        type_code=entry.get("t"),
        lat=entry.get("lat"),
        lon=entry.get("lon"),
        altitude_ft=altitude,
        ground_speed_kt=entry.get("gs"),
        track_deg=entry.get("track"),
        squawk=entry.get("squawk"),
        on_ground=on_ground,
        is_tanker=is_tanker,
        observed_at=now,
    )


@dataclass
class _SimJet:
    hex_id: str
    callsign: str | None
    registration: str
    type_code: str
    lat: float
    lon: float
    altitude_ft: int
    heading: float
    launched_at_tick: int
    squawk: str = "2000"
    on_ground: bool = False
    is_tanker: bool = False
    ground_speed_kt: float | None = None
    force_heading_jump: bool = False


# Routine background fleet.
_DEMO_FLEET = [
    ("ad1001", "N711SW", "GLF6", 34.0, -118.0),
    ("ad1002", "N88WA", "GL7T", 41.0, -87.0),
    ("ad1003", "N1KE", "G280", 33.0, -97.0),
    ("ad1004", "N360MC", "FA8X", 40.0, -105.0),
    ("ad1005", "N2N2", "CL60", 39.0, -77.0),
    ("ad1006", "N77VJ", "C750", 32.0, -110.0),
    ("ad1007", "N550GD", "GLF5", 37.0, -122.0),
    ("ad1008", "N604EP", "CL60", 42.0, -83.0),
]

# Watched HNW tails from the public watchlist module.
_WATCHED_STILL = [
    # Musk/Gates style: sit still until the scramble.
    ("admusk", "N628TS", "N628TS", "GLF6", 30.3, -97.7),
    ("adgate", "N194WM", "N194WM", "GLF5", 47.6, -122.3),
]

_PRIVACY_HEAVY = [
    # Bezos/Zuck style: already airborne toward Hawaii privacy destinations.
    ("adbezos", "N271DV", "N271DV", "GLF6", 21.5, -157.0),
    ("adzuck", "N688ZS", "N688ZS", "GLF6", 22.3, -159.3),
]

_SURGE_FLEET = [
    ("ad2001", "N1QZ", "GLF6"),
    ("ad2002", "N287WM", "GL7T"),
    ("ad2003", None, "FA7X"),
    ("ad2004", "N42PE", "GLF6"),
    ("ad2005", None, "GLEX"),
    ("ad2006", "N313RG", "CL35"),
    ("ad2007", "N100ES", "GA6C"),
    ("ad2008", "N7600K", "C700"),
]


@dataclass
class DemoScannerBackend:
    """Simulated fleet covering scramble, Hawaii quiet, tanker, and maneuvers."""

    state: RadarState
    interval: float = 2.0
    surge_at: int = 14

    def __post_init__(self) -> None:
        random.seed(20260721)
        self._fleet: list[_SimJet] = []
        for hex_id, callsign, type_code, lat, lon in _DEMO_FLEET:
            self._fleet.append(
                _SimJet(
                    hex_id=hex_id,
                    callsign=callsign,
                    registration=callsign,
                    type_code=type_code,
                    lat=lat,
                    lon=lon,
                    altitude_ft=random.randrange(37000, 45000, 1000),
                    heading=random.uniform(0, 360),
                    launched_at_tick=0,
                )
            )
        for hex_id, callsign, registration, type_code, lat, lon in _WATCHED_STILL:
            self._fleet.append(
                _SimJet(
                    hex_id=hex_id,
                    callsign=callsign,
                    registration=registration,
                    type_code=type_code,
                    lat=lat,
                    lon=lon,
                    altitude_ft=0,
                    heading=90.0,
                    launched_at_tick=0,
                    on_ground=True,
                )
            )
        for hex_id, callsign, registration, type_code, lat, lon in _PRIVACY_HEAVY:
            self._fleet.append(
                _SimJet(
                    hex_id=hex_id,
                    callsign=callsign,
                    registration=registration,
                    type_code=type_code,
                    lat=lat,
                    lon=lon,
                    altitude_ft=12000,
                    heading=250.0,
                    launched_at_tick=0,
                )
            )
        self._surge_pool = list(_SURGE_FLEET)
        self._tanker_spawned = False

    async def run(self) -> None:
        LOGGER.info("Starting demo ADS-B simulator (surge begins at tick %d)", self.surge_at)
        tick = 0
        while True:
            tick += 1
            self._advance(tick)
            observations = [self._observe(jet, tick) for jet in self._fleet]
            await self.state.ingest_cycle(observations)
            await asyncio.sleep(self.interval)

    def _advance(self, tick: int) -> None:
        # Privacy-heavy jets descend into Kauai / Maui and then leave coverage.
        for jet in self._fleet:
            if jet.hex_id == "adzuck" and tick == self.surge_at - 2:
                jet.lat, jet.lon, jet.altitude_ft = 22.10, -159.52, 2500
            if jet.hex_id == "adbezos" and tick == self.surge_at - 1:
                jet.lat, jet.lon, jet.altitude_ft = 20.85, -156.45, 1800
            if jet.hex_id in {"adzuck", "adbezos"} and tick == self.surge_at:
                # Drop off ADS-B by moving them far and marking for removal via stale.
                jet.lat, jet.lon = jet.lat, jet.lon  # stay put; we remove them below

        if tick == self.surge_at:
            # Remove privacy jets from the feed so they "go quiet" near Hawaii.
            self._fleet = [j for j in self._fleet if j.hex_id not in {"adzuck", "adbezos"}]
            # Reactive watched jets scramble.
            for jet in self._fleet:
                if jet.hex_id in {"admusk", "adgate"}:
                    jet.on_ground = False
                    jet.altitude_ft = 4000
                    jet.launched_at_tick = tick
                    jet.ground_speed_kt = 320

        if tick < self.surge_at:
            return

        for _ in range(3):
            if not self._surge_pool:
                break
            hex_id, callsign, type_code = self._surge_pool.pop(0)
            self._fleet.append(
                _SimJet(
                    hex_id=hex_id,
                    callsign=callsign,
                    registration=callsign or f"reg-{hex_id}",
                    type_code=type_code,
                    lat=random.uniform(38.0, 41.0),
                    lon=random.uniform(-78.0, -74.0),
                    altitude_ft=random.randrange(4000, 9000, 500),
                    heading=random.uniform(0, 360),
                    launched_at_tick=tick,
                )
            )

        if tick == self.surge_at + 1 and not self._tanker_spawned:
            self._tanker_spawned = True
            # Place a tanker next to the first routine jet.
            host = self._fleet[0]
            self._fleet.append(
                _SimJet(
                    hex_id="adtank1",
                    callsign="ROCC01",
                    registration="60-0341",
                    type_code="K35R",
                    lat=host.lat + 0.05,
                    lon=host.lon + 0.05,
                    altitude_ft=host.altitude_ft,
                    heading=host.heading,
                    launched_at_tick=tick,
                    is_tanker=True,
                    ground_speed_kt=450,
                )
            )
            # Force a high-speed hard-turn on another jet.
            self._fleet[1].ground_speed_kt = 620
            self._fleet[1].force_heading_jump = True

        if tick == self.surge_at + 2:
            self._fleet[0].squawk = "7700"

    def _observe(self, jet: _SimJet, tick: int) -> JetObservation:
        if not jet.on_ground:
            speed_deg = 0.01 if jet.is_tanker else 0.008
            if jet.force_heading_jump:
                jet.heading = (jet.heading + 70) % 360
                jet.force_heading_jump = False
            jet.lat += math.cos(math.radians(jet.heading)) * speed_deg
            jet.lon += math.sin(math.radians(jet.heading)) * speed_deg
            if jet.launched_at_tick and tick - jet.launched_at_tick < 12 and not jet.is_tanker:
                jet.altitude_ft += random.randrange(1500, 2500, 100)
        gs = jet.ground_speed_kt
        if gs is None:
            gs = random.uniform(430, 520) if not jet.on_ground else 0.0
        return JetObservation(
            hex_id=jet.hex_id,
            callsign=jet.callsign,
            registration=jet.registration,
            type_code=jet.type_code,
            lat=round(jet.lat, 5),
            lon=round(jet.lon, 5),
            altitude_ft=None if jet.on_ground else jet.altitude_ft,
            ground_speed_kt=round(gs, 1),
            track_deg=round(jet.heading, 1),
            squawk=jet.squawk,
            on_ground=jet.on_ground,
            is_tanker=jet.is_tanker,
            observed_at=datetime.now(UTC),
        )
