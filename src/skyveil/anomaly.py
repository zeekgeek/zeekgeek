"""Flight anomaly scoring.

Every tracked flight is scored each poll cycle against four independent
lenses:

- ``emergency``    — a declared in-flight emergency (ADS-B emergency field or
                      squawk 7500/7600/7700)
- ``experimental``  — signs of a test/prototype/research flight (test-range
                      loitering, test callsigns, unusual altitude, space/UAV
                      emitter categories)
- ``cloaked``       — signs the broadcast is anonymized or inconsistent
                      (FAA Privacy ICAO Address, LADD opt-out, degraded
                      position integrity, a hex/registration nation
                      mismatch, identity fields changing mid-flight)
- ``erratic``       — kinematics outside the normal envelope (extreme climb,
                      hard turns, overspeed for the aircraft's own category,
                      a position jump inconsistent with reported speed,
                      sustained circling)

Triggers accumulate into a single 0-100 severity score per flight. None of
this proves foul play, a secret program, or equipment failure — ADS-B is
public, unverified, and receiver coverage is uneven. Treat every detection
as a lead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .reference import (
    CATEGORY_LABELS,
    CATEGORY_SPEED_CEILING_KT,
    DEFAULT_SPEED_CEILING_KT,
    TEST_CALLSIGN_PATTERNS,
    TEST_RANGES,
    haversine_nm,
    hex_nation,
    registration_nation,
)

EMERGENCY_SQUAWKS = {
    "7500": "unlawful interference (hijack code)",
    "7600": "radio failure",
    "7700": "general emergency",
}

EMERGENCY_FIELD_LABELS = {
    "general": "declared general emergency",
    "lifeguard": "medical / lifeguard priority",
    "minfuel": "minimum fuel state",
    "nordo": "no radio (NORDO)",
    "unlawful": "unlawful interference (hijack)",
    "downed": "aircraft down",
    "reserved": "reserved emergency code",
}

EXTREME_ALTITUDE_FT = 51000
EXTREME_CLIMB_FPM = 6000.0
HARD_TURN_DEG = 60.0
LOW_INTEGRITY_NIC = 1
LOITER_HEADING_STD_DEG = 45.0
LOITER_MIN_SAMPLES = 6
LOITER_MAX_DISPLACEMENT_NM = 8.0
POSITION_JUMP_SLACK_KT = 120.0
POSITION_JUMP_MIN_SECONDS = 5.0

CATEGORIES = ("emergency", "experimental", "cloaked", "erratic")


@dataclass(frozen=True)
class Trigger:
    code: str
    category: str
    message: str
    weight: float


@dataclass
class FlightSnapshot:
    """Fields the anomaly engine needs for one flight at one poll cycle."""

    hex_id: str
    identity: str
    callsign: str | None
    registration: str | None
    type_code: str | None
    emitter_category: str | None
    lat: float | None
    lon: float | None
    altitude_ft: int | None
    ground_speed_kt: float | None
    track_deg: float | None
    baro_rate_fpm: float | None
    squawk: str | None
    emergency_field: str | None
    nic: int | None
    nac_p: int | None
    on_ground: bool
    is_pia: bool
    is_ladd: bool
    is_mil: bool
    previous_track_deg: float | None
    previous_lat: float | None
    previous_lon: float | None
    previous_registration: str | None
    previous_type_code: str | None
    seconds_since_previous: float | None
    recent_headings: list[float] = field(default_factory=list)
    recent_positions: list[tuple[float, float]] = field(default_factory=list)


def evaluate_flight(flight: FlightSnapshot) -> list[Trigger]:
    """Return every anomaly trigger a single flight trips this cycle."""
    triggers: list[Trigger] = []
    triggers.extend(_emergency_triggers(flight))
    triggers.extend(_experimental_triggers(flight))
    triggers.extend(_cloaked_triggers(flight))
    triggers.extend(_erratic_triggers(flight))
    return triggers


def score_triggers(triggers: list[Trigger]) -> tuple[float, str | None]:
    """Combine triggers into one 0-100 severity score and a dominant category."""
    if not triggers:
        return 0.0, None
    # Diminishing returns: the strongest trigger counts in full, the rest taper.
    ordered = sorted(triggers, key=lambda t: t.weight, reverse=True)
    score = 0.0
    decay = 1.0
    for trigger in ordered:
        score += trigger.weight * decay
        decay *= 0.4
    dominant = ordered[0].category
    return round(min(score, 100.0), 1), dominant


def _emergency_triggers(flight: FlightSnapshot) -> list[Trigger]:
    triggers: list[Trigger] = []
    field_value = (flight.emergency_field or "none").lower()
    if field_value not in ("none", "no emergency", ""):
        label = EMERGENCY_FIELD_LABELS.get(field_value, field_value)
        triggers.append(
            Trigger(
                "emergency-declared",
                "emergency",
                f"{flight.identity} is broadcasting a declared emergency: {label}",
                100.0,
            )
        )
    if flight.squawk in EMERGENCY_SQUAWKS:
        triggers.append(
            Trigger(
                "emergency-squawk",
                "emergency",
                f"{flight.identity} is squawking {flight.squawk}: {EMERGENCY_SQUAWKS[flight.squawk]}",
                95.0,
            )
        )
    return triggers


def _experimental_triggers(flight: FlightSnapshot) -> list[Trigger]:
    triggers: list[Trigger] = []
    callsign = (flight.callsign or "").upper()
    if any(pattern in callsign for pattern in TEST_CALLSIGN_PATTERNS):
        triggers.append(
            Trigger(
                "test-callsign",
                "experimental",
                f"{flight.identity} is flying under a test/research-style callsign",
                55.0,
            )
        )

    if flight.emitter_category in ("B6", "B7"):
        label = CATEGORY_LABELS.get(flight.emitter_category, flight.emitter_category)
        weight = 75.0 if flight.emitter_category == "B7" else 40.0
        triggers.append(
            Trigger(
                "unusual-emitter-category",
                "experimental",
                f"{flight.identity} is self-reporting an ADS-B emitter category of {label} ({flight.emitter_category})",
                weight,
            )
        )

    if (
        flight.altitude_ft is not None
        and flight.altitude_ft >= EXTREME_ALTITUDE_FT
        and not flight.on_ground
    ):
        triggers.append(
            Trigger(
                "extreme-altitude",
                "experimental",
                f"{flight.identity} is at FL{int(flight.altitude_ft / 100):03d}, above the normal civil ceiling",
                50.0,
            )
        )

    if (
        not flight.on_ground
        and not callsign
        and not flight.type_code
        and flight.lat is not None
        and flight.lon is not None
    ):
        triggers.append(
            Trigger(
                "unclassified-airframe",
                "experimental",
                f"{flight.identity} is airborne with no callsign or aircraft-type broadcast",
                40.0,
            )
        )

    if not flight.on_ground and flight.lat is not None and flight.lon is not None:
        for test_range in TEST_RANGES:
            distance = haversine_nm(flight.lat, flight.lon, test_range.lat, test_range.lon)
            if distance > test_range.radius_nm:
                continue
            loitering = _is_loitering(flight)
            if loitering or not callsign:
                reason = "loitering" if loitering else "no callsign"
                triggers.append(
                    Trigger(
                        "test-range-presence",
                        "experimental",
                        f"{flight.identity} is {reason} inside {test_range.name} test airspace",
                        60.0 if loitering else 45.0,
                    )
                )
            break
    return triggers


def _cloaked_triggers(flight: FlightSnapshot) -> list[Trigger]:
    triggers: list[Trigger] = []
    if flight.is_pia:
        triggers.append(
            Trigger(
                "privacy-icao-address",
                "cloaked",
                f"{flight.identity} is broadcasting from an FAA Privacy ICAO Address (temporary anonymized hex)",
                65.0,
            )
        )
    if flight.is_ladd:
        triggers.append(
            Trigger(
                "ladd-opt-out",
                "cloaked",
                f"{flight.identity} is on the LADD list (opted out of public tracking, still broadcasting)",
                40.0,
            )
        )

    if (
        flight.nic is not None
        and flight.nic <= LOW_INTEGRITY_NIC
        and not flight.on_ground
        and (flight.ground_speed_kt or 0) > 50
    ):
        triggers.append(
            Trigger(
                "degraded-position-integrity",
                "cloaked",
                f"{flight.identity} is moving with very low position-integrity figures (NIC {flight.nic}) "
                "— malfunctioning transponder or spoofed position are both possible",
                35.0,
            )
        )

    nation_by_hex = hex_nation(flight.hex_id)
    nation_by_reg = registration_nation(flight.registration)
    if nation_by_hex and nation_by_reg and nation_by_hex != nation_by_reg:
        triggers.append(
            Trigger(
                "hex-nation-mismatch",
                "cloaked",
                f"{flight.identity}: registration {flight.registration} looks {nation_by_reg}-issued but its "
                f"ICAO hex {flight.hex_id} falls in the {nation_by_hex} allocation block (unverified heuristic)",
                45.0,
            )
        )

    if (
        flight.previous_registration
        and flight.registration
        and flight.previous_registration != flight.registration
    ):
        triggers.append(
            Trigger(
                "identity-churn",
                "cloaked",
                f"{flight.identity}: registration changed mid-flight ({flight.previous_registration} -> "
                f"{flight.registration}) on the same ICAO hex",
                50.0,
            )
        )
    elif (
        flight.previous_type_code
        and flight.type_code
        and flight.previous_type_code != flight.type_code
    ):
        triggers.append(
            Trigger(
                "identity-churn",
                "cloaked",
                f"{flight.identity}: aircraft type changed mid-flight ({flight.previous_type_code} -> "
                f"{flight.type_code}) on the same ICAO hex",
                50.0,
            )
        )
    return triggers


def _erratic_triggers(flight: FlightSnapshot) -> list[Trigger]:
    triggers: list[Trigger] = []
    if flight.on_ground:
        return triggers

    if flight.baro_rate_fpm is not None and abs(flight.baro_rate_fpm) >= EXTREME_CLIMB_FPM:
        direction = "climbing" if flight.baro_rate_fpm > 0 else "descending"
        triggers.append(
            Trigger(
                "extreme-vertical-rate",
                "erratic",
                f"{flight.identity} is {direction} at {abs(flight.baro_rate_fpm):.0f} ft/min",
                min(45.0 * (abs(flight.baro_rate_fpm) / EXTREME_CLIMB_FPM), 70.0),
            )
        )

    if (
        flight.track_deg is not None
        and flight.previous_track_deg is not None
        and (flight.ground_speed_kt or 0) > 100
    ):
        delta = _heading_delta(flight.previous_track_deg, flight.track_deg)
        if delta >= HARD_TURN_DEG:
            triggers.append(
                Trigger(
                    "hard-turn",
                    "erratic",
                    f"{flight.identity} changed heading {delta:.0f}° in one cycle at "
                    f"{flight.ground_speed_kt:.0f} kt",
                    min(40.0 * (delta / HARD_TURN_DEG), 65.0),
                )
            )

    ceiling = CATEGORY_SPEED_CEILING_KT.get(flight.emitter_category or "", DEFAULT_SPEED_CEILING_KT)
    if flight.ground_speed_kt is not None and flight.ground_speed_kt >= ceiling:
        category_label = CATEGORY_LABELS.get(flight.emitter_category or "", "this aircraft category")
        triggers.append(
            Trigger(
                "overspeed-for-category",
                "erratic",
                f"{flight.identity} is doing {flight.ground_speed_kt:.0f} kt, above the norm for {category_label}",
                min(50.0 * (flight.ground_speed_kt / ceiling), 70.0),
            )
        )

    jump = _position_jump_trigger(flight)
    if jump is not None:
        triggers.append(jump)

    if _is_loitering(flight):
        triggers.append(
            Trigger(
                "sustained-loiter",
                "erratic",
                f"{flight.identity} has been circling/holding within a tight area for several poll cycles",
                35.0,
            )
        )
    return triggers


def _position_jump_trigger(flight: FlightSnapshot) -> Trigger | None:
    if (
        flight.lat is None
        or flight.lon is None
        or flight.previous_lat is None
        or flight.previous_lon is None
        or flight.seconds_since_previous is None
        or flight.seconds_since_previous < POSITION_JUMP_MIN_SECONDS
    ):
        return None
    distance_nm = haversine_nm(flight.previous_lat, flight.previous_lon, flight.lat, flight.lon)
    hours = flight.seconds_since_previous / 3600.0
    implied_kt = distance_nm / hours if hours > 0 else 0.0
    reported_kt = flight.ground_speed_kt or 0.0
    if implied_kt <= reported_kt + POSITION_JUMP_SLACK_KT:
        return None
    return Trigger(
        "position-discontinuity",
        "erratic",
        f"{flight.identity} jumped {distance_nm:.0f} nm in {flight.seconds_since_previous:.0f}s "
        f"(implies {implied_kt:.0f} kt vs {reported_kt:.0f} kt reported) — possible spoofed or dropped track",
        min(60.0 * (implied_kt / max(reported_kt + POSITION_JUMP_SLACK_KT, 1.0)), 80.0),
    )


def _is_loitering(flight: FlightSnapshot) -> bool:
    positions = flight.recent_positions
    headings = flight.recent_headings
    if len(positions) < LOITER_MIN_SAMPLES or len(headings) < LOITER_MIN_SAMPLES:
        return False
    first = positions[0]
    max_displacement = max(haversine_nm(first[0], first[1], lat, lon) for lat, lon in positions)
    if max_displacement > LOITER_MAX_DISPLACEMENT_NM:
        return False
    return _heading_std(headings) >= LOITER_HEADING_STD_DEG


def _heading_std(headings: list[float]) -> float:
    if len(headings) < 2:
        return 0.0
    # Circular deviation: mean of consecutive absolute heading deltas.
    deltas = [_heading_delta(headings[i - 1], headings[i]) for i in range(1, len(headings))]
    return sum(deltas) / len(deltas)


def _heading_delta(previous: float, current: float) -> float:
    delta = abs(current - previous) % 360.0
    return min(delta, 360.0 - delta)
