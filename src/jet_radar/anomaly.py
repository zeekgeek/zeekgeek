"""Historical baseline, ADS-B anomaly, and strange-event detection.

The radar samples airborne business-jet volume every poll cycle and scores it
against a rolling historical baseline. It also inspects individual flight
kinematics and military-tanker proximity for ADS-B anomalies:

- ``traffic-surge`` / ``departure-wave``: volume far above history
- ``watchlist-scramble``: several watched HNW aircraft take off together
- ``high-speed-maneuver``: ground speed or turn rate far beyond cruise norms
- ``tanker-rendezvous``: a bizjet loitering near a tanker at similar altitude
- ``emergency-squawk``: 7500 / 7600 / 7700
- ``dark-flight-spike``: unusual share of flights with no callsign
- ``privacy-landing``: a watched jet going quiet inside a known privacy region

Triggers pile up in a short window. Enough of them fire the strange-event
alarm. These are statistical hints from public ADS-B — holidays, weather,
receiver coverage, and LLC shells all muddy the signal.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import fmean, pstdev

from .watchlist import haversine_nm

STRANGE_SQUAWKS = {
    "7500": "unlawful interference (hijack code)",
    "7600": "radio failure",
    "7700": "general emergency",
}

MIN_STD = 1.0
DEFAULT_SIGMA = 3.0
DEFAULT_BASELINE_WINDOW = 240
DEFAULT_MIN_BASELINE_SAMPLES = 10
DEFAULT_TRIGGER_WINDOW = 8
DEFAULT_TRIGGER_THRESHOLD = 3

DARK_SHARE_THRESHOLD = 0.35
DARK_MIN_AIRBORNE = 8

# Ground-speed (kt) and turn-rate (deg/cycle) thresholds for "high-speed maneuver".
HIGH_SPEED_KT = 580.0
HIGH_TURN_DEG = 55.0
HIGH_CLIMB_FPM = 5500.0

# Bizjet within this distance/altitude of a tanker counts as a possible rendezvous.
TANKER_RANGE_NM = 12.0
TANKER_ALT_DELTA_FT = 4000.0

# Two or more watched "reactive" jets departing in one window = scramble.
WATCHLIST_SCRAMBLE_MIN = 2


@dataclass(frozen=True)
class Trigger:
    code: str
    detail: str
    score: float


@dataclass(frozen=True)
class TrackSnapshot:
    """Minimal per-jet fields needed for anomaly scoring."""

    hex_id: str
    identity: str
    registration: str | None
    lat: float | None
    lon: float | None
    altitude_ft: int | None
    ground_speed_kt: float | None
    track_deg: float | None
    previous_track_deg: float | None
    previous_altitude_ft: int | None
    cycle_seconds: float
    watched_label: str | None
    movement_style: str | None
    just_became_airborne: bool
    just_went_quiet: bool
    is_tanker: bool = False


class MovementBaseline:
    """Rolling history of per-cycle jet counts with z-score scoring."""

    def __init__(
        self,
        window: int = DEFAULT_BASELINE_WINDOW,
        min_samples: int = DEFAULT_MIN_BASELINE_SAMPLES,
    ) -> None:
        self.min_samples = min_samples
        self._airborne: deque[int] = deque(maxlen=window)
        self._departures: deque[int] = deque(maxlen=window)

    @property
    def ready(self) -> bool:
        return len(self._airborne) >= self.min_samples

    def score(self, airborne: int, new_airborne: int) -> tuple[float | None, float | None]:
        if not self.ready:
            return None, None
        return (
            _zscore(airborne, list(self._airborne)),
            _zscore(new_airborne, list(self._departures)),
        )

    def record(self, airborne: int, new_airborne: int) -> None:
        self._airborne.append(airborne)
        self._departures.append(new_airborne)

    def stats(self) -> dict[str, float | int | bool | None]:
        airborne = list(self._airborne)
        return {
            "samples": len(airborne),
            "ready": self.ready,
            "airborne_mean": round(fmean(airborne), 2) if airborne else None,
            "airborne_std": round(max(pstdev(airborne), MIN_STD), 2) if len(airborne) > 1 else None,
        }


def evaluate_triggers(
    *,
    airborne: int,
    new_airborne: int,
    airborne_z: float | None,
    departures_z: float | None,
    emergency_squawks: list[tuple[str, str]],
    dark_flights: int,
    sigma: float,
    tracks: list[TrackSnapshot] | None = None,
    privacy_landings: list[tuple[str, str]] | None = None,
) -> list[Trigger]:
    """Return the movement / ADS-B anomaly triggers for one poll cycle."""
    triggers: list[Trigger] = []
    tracks = tracks or []
    privacy_landings = privacy_landings or []

    if airborne_z is not None and airborne_z >= sigma:
        triggers.append(
            Trigger(
                "traffic-surge",
                f"{airborne} jets airborne is {airborne_z:.1f} sigma above the historical baseline",
                airborne_z,
            )
        )
    if departures_z is not None and departures_z >= sigma and new_airborne >= 2:
        triggers.append(
            Trigger(
                "departure-wave",
                f"{new_airborne} new jets took to the air this cycle ({departures_z:.1f} sigma above normal)",
                departures_z,
            )
        )
    for identity, squawk in emergency_squawks:
        triggers.append(
            Trigger(
                "emergency-squawk",
                f"{identity} squawking {squawk}: {STRANGE_SQUAWKS[squawk]}",
                sigma,
            )
        )
    if airborne >= DARK_MIN_AIRBORNE and dark_flights / airborne >= DARK_SHARE_THRESHOLD:
        triggers.append(
            Trigger(
                "dark-flight-spike",
                f"{dark_flights} of {airborne} airborne jets are flying with no callsign",
                sigma,
            )
        )

    scramble = [
        t
        for t in tracks
        if t.just_became_airborne and t.watched_label and t.movement_style == "reactive"
    ]
    if len(scramble) >= WATCHLIST_SCRAMBLE_MIN:
        names = ", ".join(sorted({t.watched_label for t in scramble}))
        triggers.append(
            Trigger(
                "watchlist-scramble",
                f"{len(scramble)} watched reactive jets departed together ({names})",
                float(len(scramble)),
            )
        )

    for track in tracks:
        if track.is_tanker:
            continue
        maneuver = classify_maneuver(track)
        if maneuver:
            triggers.append(maneuver)

    for rendezvous in find_tanker_rendezvous(tracks):
        triggers.append(rendezvous)

    for identity, place in privacy_landings:
        triggers.append(
            Trigger(
                "privacy-landing",
                f"{identity} went quiet near privacy destination {place}",
                sigma,
            )
        )

    return triggers


def classify_maneuver(track: TrackSnapshot) -> Trigger | None:
    """Flag high-speed, hard-turn, or extreme climb ADS-B kinematics."""
    reasons: list[str] = []
    score = 0.0
    if track.ground_speed_kt is not None and track.ground_speed_kt >= HIGH_SPEED_KT:
        reasons.append(f"{track.ground_speed_kt:.0f} kt ground speed")
        score = max(score, track.ground_speed_kt / HIGH_SPEED_KT)
    if (
        track.track_deg is not None
        and track.previous_track_deg is not None
        and _heading_delta(track.previous_track_deg, track.track_deg) >= HIGH_TURN_DEG
    ):
        delta = _heading_delta(track.previous_track_deg, track.track_deg)
        reasons.append(f"{delta:.0f}° heading change")
        score = max(score, delta / HIGH_TURN_DEG)
    if (
        track.altitude_ft is not None
        and track.previous_altitude_ft is not None
        and track.cycle_seconds > 0
    ):
        fpm = (track.altitude_ft - track.previous_altitude_ft) / (track.cycle_seconds / 60.0)
        if fpm >= HIGH_CLIMB_FPM:
            reasons.append(f"{fpm:.0f} fpm climb")
            score = max(score, fpm / HIGH_CLIMB_FPM)
    if not reasons:
        return None
    return Trigger(
        "high-speed-maneuver",
        f"{track.identity} unusual ADS-B kinematics: {', '.join(reasons)}",
        round(score, 2),
    )


def find_tanker_rendezvous(tracks: list[TrackSnapshot]) -> list[Trigger]:
    """Bizjets near a tanker at similar altitude → possible aerial-refuel contact."""
    tankers = [t for t in tracks if t.is_tanker and t.lat is not None and t.lon is not None]
    jets = [t for t in tracks if not t.is_tanker and t.lat is not None and t.lon is not None]
    triggers: list[Trigger] = []
    seen: set[str] = set()
    for tanker in tankers:
        for jet in jets:
            assert tanker.lat is not None and tanker.lon is not None
            assert jet.lat is not None and jet.lon is not None
            distance = haversine_nm(tanker.lat, tanker.lon, jet.lat, jet.lon)
            if distance > TANKER_RANGE_NM:
                continue
            if tanker.altitude_ft is None or jet.altitude_ft is None:
                continue
            if abs(tanker.altitude_ft - jet.altitude_ft) > TANKER_ALT_DELTA_FT:
                continue
            key = f"{jet.hex_id}:{tanker.hex_id}"
            if key in seen:
                continue
            seen.add(key)
            triggers.append(
                Trigger(
                    "tanker-rendezvous",
                    f"{jet.identity} within {distance:.1f} nm of tanker {tanker.identity} "
                    f"near FL{int(jet.altitude_ft / 100):03d}",
                    round(TANKER_RANGE_NM / max(distance, 0.1), 2),
                )
            )
    return triggers


def movement_posture(airborne_history: list[bool], *, window: int = 12) -> str:
    """Classify a watched jet as sitting-still, staging, or on-the-move."""
    if not airborne_history:
        return "unknown"
    recent = airborne_history[-window:]
    airborne_share = sum(1 for flag in recent if flag) / len(recent)
    if airborne_share >= 0.7:
        return "on-the-move"
    if airborne_share <= 0.15:
        return "sitting-still"
    return "staging"


class StrangeEventAlarm:
    """Sliding-window trigger counter with fire/release hysteresis."""

    def __init__(
        self,
        window: int = DEFAULT_TRIGGER_WINDOW,
        threshold: int = DEFAULT_TRIGGER_THRESHOLD,
    ) -> None:
        self.threshold = max(1, threshold)
        self.active = False
        self._counts: deque[int] = deque(maxlen=window)

    @property
    def recent_triggers(self) -> int:
        return sum(self._counts)

    def update(self, trigger_count: int) -> str | None:
        self._counts.append(trigger_count)
        total = self.recent_triggers
        if not self.active and total >= self.threshold:
            self.active = True
            return "fired"
        if self.active and total == 0:
            self.active = False
            return "cleared"
        return None


def _heading_delta(previous: float, current: float) -> float:
    delta = abs(current - previous) % 360.0
    return min(delta, 360.0 - delta)


def _zscore(value: int, history: list[int]) -> float:
    mean = fmean(history)
    std = max(pstdev(history) if len(history) > 1 else 0.0, MIN_STD)
    return round((value - mean) / std, 2)
