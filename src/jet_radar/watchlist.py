"""Watchlist of publicly reported HNW aircraft and privacy destinations.

Aircraft-to-person links here come from *public reporting* (FAA registration
records, journalism, flight-tracking blogs). Ownership changes, LLC shells,
and fractional programs mean attribution is imperfect — treat every match as
a lead, not proof that a named person is on board.

Destination regions are places publicly associated with high-net-worth
privacy compounds or island holdings. The radar scores how often watched
jets linger or go quiet near those regions; it does **not** assert the
existence of any underground facility or bunker.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

# ICAO type designators for aerial-refueling tankers seen on ADS-B.
TANKER_TYPES = ["K35R", "K35E", "KC10", "K46A"]


@dataclass(frozen=True)
class WatchedAircraft:
    registration: str
    label: str
    notes: str
    movement_style: str  # "reactive" | "privacy-heavy" | "routine"


@dataclass(frozen=True)
class PrivacyDestination:
    code: str
    name: str
    lat: float
    lon: float
    radius_nm: float
    notes: str


# Publicly reported registrations. Update locally as ownership changes.
WATCHLIST: list[WatchedAircraft] = [
    WatchedAircraft(
        "N628TS",
        "Elon Musk (reported)",
        "Gulfstream G650ER widely linked in public flight-tracking coverage to Musk/SpaceX travel.",
        "reactive",
    ),
    WatchedAircraft(
        "N272BG",
        "Bill Gates (historical)",
        "Historically associated with Gates/Cascade travel in public trackers; verify current registration.",
        "reactive",
    ),
    WatchedAircraft(
        "N194WM",
        "Bill Gates orbit (reported)",
        "Cascade-linked Gulfstream often cited in public flight logs.",
        "reactive",
    ),
    WatchedAircraft(
        "N271DV",
        "Jeff Bezos (reported)",
        "G650ER repeatedly linked in public reporting to Bezos travel.",
        "privacy-heavy",
    ),
    WatchedAircraft(
        "N688ZS",
        "Mark Zuckerberg (reported)",
        "Channel Enterprises / Kauai-linked traffic reported in public trackers.",
        "privacy-heavy",
    ),
    WatchedAircraft(
        "N88LJ",
        "Larry Ellison (historical)",
        "Ellison/Lanai-linked traffic has appeared under several tails over time.",
        "privacy-heavy",
    ),
]


# Regions with publicly reported HNW property or island holdings.
PRIVACY_DESTINATIONS: list[PrivacyDestination] = [
    PrivacyDestination(
        "kauai",
        "Kauai, Hawaii",
        22.0964,
        -159.5261,
        40,
        "Publicly reported Zuckerberg land holdings; popular HNW privacy destination.",
    ),
    PrivacyDestination(
        "maui",
        "Maui / Big Island corridor",
        20.7984,
        -156.3319,
        80,
        "Publicly reported Bezos Hawaii property interest and frequent VIP traffic.",
    ),
    PrivacyDestination(
        "lanai",
        "Lanai, Hawaii",
        20.8270,
        -156.9220,
        25,
        "Larry Ellison owns most of Lanai (public fact); airport LNY is a privacy hub.",
    ),
    PrivacyDestination(
        "jackson",
        "Jackson Hole / Teton",
        43.6073,
        -110.7377,
        45,
        "Ranch and compound country; heavy seasonal bizjet traffic.",
    ),
    PrivacyDestination(
        "aspen",
        "Aspen / Pitkin",
        39.2232,
        -106.8688,
        30,
        "Classic HNW ski-and-compound destination (airport ASE).",
    ),
    PrivacyDestination(
        "palm-beach",
        "Palm Beach / Wellington",
        26.6830,
        -80.0956,
        35,
        "Seasonal HNW corridor; Palm Beach International + private fields.",
    ),
    PrivacyDestination(
        "nz-south",
        "New Zealand South Island",
        -45.0312,
        168.6626,
        120,
        "Queenstown / Wanaka privacy corridor cited for tech-founder retreats.",
    ),
    PrivacyDestination(
        "montana",
        "Montana / Big Sky",
        45.2846,
        -111.4014,
        70,
        "Ranch-country privacy corridor with thin commercial coverage.",
    ),
    PrivacyDestination(
        "sun-valley",
        "Sun Valley / Hailey",
        43.5044,
        -114.2956,
        35,
        "Idaho compound country (airport SUN).",
    ),
    PrivacyDestination(
        "austin-hill",
        "Texas Hill Country / Austin",
        30.2672,
        -97.7431,
        50,
        "Austin metro + Hill Country privacy estates; Musk/tech travel corridor.",
    ),
]


def registration_lookup() -> dict[str, WatchedAircraft]:
    return {item.registration.upper(): item for item in WATCHLIST}


def match_watchlist(registration: str | None, callsign: str | None = None) -> WatchedAircraft | None:
    lookup = registration_lookup()
    if registration:
        hit = lookup.get(registration.upper().replace("-", "").strip())
        if hit:
            return hit
        # Accept N-numbers with a dash: N-628TS
        compact = registration.upper().replace("-", "").strip()
        hit = lookup.get(compact)
        if hit:
            return hit
    if callsign:
        compact = callsign.upper().replace("-", "").strip()
        return lookup.get(compact)
    return None


def nearest_privacy_destination(
    lat: float, lon: float
) -> tuple[PrivacyDestination, float] | None:
    """Return the closest privacy destination within its own radius, if any."""
    best: tuple[PrivacyDestination, float] | None = None
    for dest in PRIVACY_DESTINATIONS:
        distance = haversine_nm(lat, lon, dest.lat, dest.lon)
        if distance <= dest.radius_nm and (best is None or distance < best[1]):
            best = (dest, distance)
    return best


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_nm = 3440.065
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * radius_nm * asin(sqrt(a))
