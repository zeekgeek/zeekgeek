"""Static reference data: flight-test ranges, hex/registry blocks, category norms.

None of this is authoritative attribution. ICAO 24-bit hex allocation blocks
and ADS-B emitter categories are publicly documented, but real-world traffic
has exceptions (leased aircraft, re-registrations, receiver noise). Treat
every match here as a lead worth a second look, not a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_nm = 3440.065
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * radius_nm * asin(sqrt(a))


@dataclass(frozen=True)
class TestRange:
    code: str
    name: str
    lat: float
    lon: float
    radius_nm: float
    notes: str


# Publicly known flight-test / experimental-aircraft airspace. Loitering here
# with a non-airline-shaped callsign is a lead, not proof of a secret program.
TEST_RANGES: list[TestRange] = [
    TestRange("edwards", "Edwards AFB / NASA Armstrong", 34.9054, -117.8837, 25,
              "USAF Flight Test Center and NASA Armstrong; routine home for prototype aircraft."),
    TestRange("mojave", "Mojave Air & Space Port", 35.0590, -118.1517, 12,
              "Civilian flight-test and spaceflight hub (Scaled Composites and tenants)."),
    TestRange("chinalake", "China Lake NAWS", 35.6850, -117.6839, 30,
              "Naval Air Warfare Center weapons and systems test range."),
    TestRange("ptmugu", "Point Mugu Sea Range", 34.1199, -119.1211, 25,
              "Naval Air Warfare Center Weapons Division sea-range airspace."),
    TestRange("plant42", "Palmdale Plant 42", 34.6294, -118.0854, 12,
              "USAF/contractor flight-test airfield (Skunk Works heritage)."),
    TestRange("groomlake", "Groom Lake / Nellis restricted range", 37.2350, -115.8111, 25,
              "Restricted federal test facility; public ADS-B coverage is sparse by design."),
    TestRange("whitesands", "White Sands Missile Range", 33.0, -106.4, 45,
              "Army test and evaluation range; frequent NOTAM'd rocket and UAS activity."),
    TestRange("wallops", "NASA Wallops Flight Facility", 37.9401, -75.4664, 20,
              "NASA rocket, balloon, and UAS test range on the Virginia coast."),
    TestRange("eglin", "Eglin AFB Test Range", 30.4832, -86.5254, 30,
              "Air Force Materiel Command weapons and aircraft test range."),
    TestRange("patuxent", "NAS Patuxent River", 38.2856, -76.4118, 20,
              "Navy flight-test center (\"Pax River\") for carrier and fixed-wing programs."),
]

# Best-effort ICAO 24-bit hex allocation blocks for a handful of well-documented
# countries, paired with the registration prefixes normally issued from that
# block. Deliberately small and conservative: an unmatched pair is left alone
# rather than guessed at.
HEX_NATION_BLOCKS: list[tuple[int, int, str]] = [
    (0xA00000, 0xAFFFFF, "United States"),
    (0xC00000, 0xC3FFFF, "Canada"),
    (0x7C0000, 0x7FFFFF, "Australia"),
    (0x400000, 0x43FFFF, "United Kingdom"),
    (0x3C0000, 0x3FFFFF, "Germany"),
    (0x380000, 0x3BFFFF, "France"),
]

REGISTRATION_PREFIX_NATION: list[tuple[str, str]] = [
    ("N", "United States"),
    ("C-", "Canada"),
    ("VH-", "Australia"),
    ("G-", "United Kingdom"),
    ("D-", "Germany"),
    ("F-", "France"),
]


def hex_nation(hex_id: str) -> str | None:
    try:
        value = int(hex_id, 16)
    except ValueError:
        return None
    for start, end, nation in HEX_NATION_BLOCKS:
        if start <= value <= end:
            return nation
    return None


def registration_nation(registration: str | None) -> str | None:
    if not registration:
        return None
    upper = registration.upper()
    for prefix, nation in REGISTRATION_PREFIX_NATION:
        if upper.startswith(prefix):
            return nation
    return None


# ADS-B DO-260B emitter categories, human-readable.
CATEGORY_LABELS: dict[str, str] = {
    "A1": "light aircraft",
    "A2": "small aircraft",
    "A3": "large aircraft",
    "A4": "high-vortex large aircraft",
    "A5": "heavy aircraft",
    "A6": "high-performance / high-speed",
    "A7": "rotorcraft",
    "B1": "glider / sailplane",
    "B2": "lighter-than-air",
    "B3": "parachutist / skydiver",
    "B4": "ultralight / hang-glider / paraglider",
    "B6": "unmanned aerial vehicle",
    "B7": "space / trans-atmospheric vehicle",
}

# Rough ground-speed ceilings (kt) used only to flag outliers, not to certify
# performance envelopes. Anything without a table entry falls back to the
# default.
CATEGORY_SPEED_CEILING_KT: dict[str, float] = {
    "A1": 260.0,
    "A2": 380.0,
    "A7": 210.0,
    "B1": 150.0,
    "B4": 120.0,
    "B6": 260.0,
}
DEFAULT_SPEED_CEILING_KT = 620.0

# Callsign fragments that publicly correlate with test/experimental flights
# (manufacturer flight-test desks, FAA/NASA test callsign conventions).
TEST_CALLSIGN_PATTERNS = ("TEST", "XPRMT", "EXPER", "PROTO", "RSRCH")
