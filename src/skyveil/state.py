"""In-memory flight tracks and anomaly-score bookkeeping across poll cycles."""

from __future__ import annotations

import asyncio
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .anomaly import CATEGORIES, FlightSnapshot, Trigger, evaluate_flight, score_triggers

DETECTION_SCORE_THRESHOLD = 30.0
TRAIL_LENGTH = 40
HEADING_HISTORY_LENGTH = 8
POSITION_HISTORY_LENGTH = 8
HISTORY_LENGTH = 240
EVENT_LOG_LENGTH = 300


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass
class FlightObservation:
    hex_id: str
    callsign: str | None = None
    registration: str | None = None
    type_code: str | None = None
    emitter_category: str | None = None
    lat: float | None = None
    lon: float | None = None
    altitude_ft: int | None = None
    ground_speed_kt: float | None = None
    track_deg: float | None = None
    baro_rate_fpm: float | None = None
    squawk: str | None = None
    emergency_field: str | None = None
    nic: int | None = None
    nac_p: int | None = None
    on_ground: bool = False
    is_pia: bool = False
    is_ladd: bool = False
    is_mil: bool = False
    observed_at: datetime = field(default_factory=utc_now)


@dataclass
class FlightTrack:
    hex_id: str
    first_seen: datetime
    last_seen: datetime
    callsign: str | None = None
    registration: str | None = None
    type_code: str | None = None
    emitter_category: str | None = None
    lat: float | None = None
    lon: float | None = None
    altitude_ft: int | None = None
    ground_speed_kt: float | None = None
    track_deg: float | None = None
    baro_rate_fpm: float | None = None
    squawk: str | None = None
    emergency_field: str | None = None
    nic: int | None = None
    nac_p: int | None = None
    on_ground: bool = False
    is_pia: bool = False
    is_ladd: bool = False
    is_mil: bool = False
    present: bool = True
    seen_count: int = 0
    previous_track_deg: float | None = None
    previous_lat: float | None = None
    previous_lon: float | None = None
    previous_registration: str | None = None
    previous_type_code: str | None = None
    score: float = 0.0
    dominant_category: str | None = None
    triggers: list[Trigger] = field(default_factory=list)
    recent_headings: deque[float] = field(default_factory=lambda: deque(maxlen=HEADING_HISTORY_LENGTH))
    recent_positions: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=POSITION_HISTORY_LENGTH)
    )
    trail: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=TRAIL_LENGTH))
    _pending_elapsed: float | None = field(default=None, repr=False)

    def identity(self) -> str:
        return (self.callsign or "").strip() or self.registration or self.hex_id

    def apply(self, obs: FlightObservation) -> float | None:
        """Update from a new observation. Returns seconds since the last fix."""
        elapsed = (obs.observed_at - self.last_seen).total_seconds() if self.seen_count else None
        self._pending_elapsed = elapsed
        self.previous_track_deg = self.track_deg
        self.previous_lat = self.lat
        self.previous_lon = self.lon
        self.previous_registration = self.registration
        self.previous_type_code = self.type_code

        self.last_seen = obs.observed_at
        self.seen_count += 1
        self.present = True
        self.callsign = obs.callsign or self.callsign
        self.registration = obs.registration or self.registration
        self.type_code = obs.type_code or self.type_code
        self.emitter_category = obs.emitter_category or self.emitter_category
        if obs.lat is not None:
            self.lat = obs.lat
        if obs.lon is not None:
            self.lon = obs.lon
        self.altitude_ft = obs.altitude_ft
        self.ground_speed_kt = obs.ground_speed_kt
        self.track_deg = obs.track_deg
        self.baro_rate_fpm = obs.baro_rate_fpm
        self.squawk = obs.squawk
        self.emergency_field = obs.emergency_field
        self.nic = obs.nic
        self.nac_p = obs.nac_p
        self.on_ground = obs.on_ground
        self.is_pia = obs.is_pia or self.is_pia
        self.is_ladd = obs.is_ladd or self.is_ladd
        self.is_mil = obs.is_mil or self.is_mil

        if obs.track_deg is not None:
            self.recent_headings.append(obs.track_deg)
        if obs.lat is not None and obs.lon is not None:
            self.recent_positions.append((obs.lat, obs.lon))
            self.trail.append(
                {"lat": obs.lat, "lon": obs.lon, "alt": obs.altitude_ft, "at": iso_time(obs.observed_at)}
            )
        return elapsed

    def snapshot_field(self) -> FlightSnapshot:
        return FlightSnapshot(
            hex_id=self.hex_id,
            identity=self.identity(),
            callsign=self.callsign,
            registration=self.registration,
            type_code=self.type_code,
            emitter_category=self.emitter_category,
            lat=self.lat,
            lon=self.lon,
            altitude_ft=self.altitude_ft,
            ground_speed_kt=self.ground_speed_kt,
            track_deg=self.track_deg,
            baro_rate_fpm=self.baro_rate_fpm,
            squawk=self.squawk,
            emergency_field=self.emergency_field,
            nic=self.nic,
            nac_p=self.nac_p,
            on_ground=self.on_ground,
            is_pia=self.is_pia,
            is_ladd=self.is_ladd,
            is_mil=self.is_mil,
            previous_track_deg=self.previous_track_deg,
            previous_lat=self.previous_lat,
            previous_lon=self.previous_lon,
            previous_registration=self.previous_registration,
            previous_type_code=self.previous_type_code,
            seconds_since_previous=self._pending_elapsed,
            recent_headings=list(self.recent_headings),
            recent_positions=list(self.recent_positions),
        )

    def mark_left_if_stale(self, now: datetime, stale_after: float) -> bool:
        if not self.present:
            return False
        if (now - self.last_seen).total_seconds() <= stale_after:
            return False
        self.present = False
        return True

    def to_dict(self, now: datetime) -> dict[str, Any]:
        return {
            "hex": self.hex_id,
            "identity": self.identity(),
            "callsign": (self.callsign or "").strip() or None,
            "registration": self.registration,
            "type": self.type_code,
            "category": self.emitter_category,
            "lat": self.lat,
            "lon": self.lon,
            "altitude_ft": self.altitude_ft,
            "ground_speed_kt": self.ground_speed_kt,
            "track_deg": self.track_deg,
            "baro_rate_fpm": self.baro_rate_fpm,
            "squawk": self.squawk,
            "emergency_field": self.emergency_field,
            "on_ground": self.on_ground,
            "present": self.present,
            "is_pia": self.is_pia,
            "is_ladd": self.is_ladd,
            "is_mil": self.is_mil,
            "seen_count": self.seen_count,
            "first_seen": iso_time(self.first_seen),
            "last_seen": iso_time(self.last_seen),
            "stale_seconds": round((now - self.last_seen).total_seconds(), 1),
            "score": self.score,
            "dominant_category": self.dominant_category,
            "triggers": [
                {"code": t.code, "category": t.category, "message": t.message, "weight": t.weight}
                for t in self.triggers
            ],
            "trail": list(self.trail),
        }


class SkyState:
    """Tracks flights across poll cycles and scores each one for anomalies."""

    def __init__(self, *, stale_after: float = 120.0, detection_threshold: float = DETECTION_SCORE_THRESHOLD) -> None:
        self.stale_after = stale_after
        self.detection_threshold = detection_threshold
        self._flights: dict[str, FlightTrack] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=EVENT_LOG_LENGTH)
        self._history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LENGTH)
        self._open_detections: set[str] = set()
        self._lock = asyncio.Lock()

    async def ingest_cycle(self, observations: list[FlightObservation]) -> list[dict[str, Any]]:
        async with self._lock:
            now = utc_now()
            emitted: list[dict[str, Any]] = []
            previously_present = set(self._flights)

            for obs in observations:
                track = self._flights.get(obs.hex_id)
                if track is None:
                    track = FlightTrack(hex_id=obs.hex_id, first_seen=obs.observed_at, last_seen=obs.observed_at)
                    self._flights[obs.hex_id] = track
                track.apply(obs)
                triggers = evaluate_flight(track.snapshot_field())
                score, dominant = score_triggers(triggers)
                track.triggers = triggers
                track.score = score
                track.dominant_category = dominant
                self._log_detection_transition(track, emitted, now)

            for hex_id, track in self._flights.items():
                if hex_id in previously_present and track.mark_left_if_stale(now, self.stale_after):
                    if hex_id in self._open_detections:
                        self._open_detections.discard(hex_id)
                        emitted.append(
                            self._event(
                                "detection-cleared",
                                track,
                                now,
                                f"{track.identity()} left ADS-B coverage while flagged",
                            )
                        )

            present = [t for t in self._flights.values() if t.present]
            airborne = [t for t in present if not t.on_ground]
            detections = sorted(
                (t for t in present if t.score >= self.detection_threshold),
                key=lambda t: t.score,
                reverse=True,
            )
            category_counts = Counter(t.dominant_category for t in detections if t.dominant_category)

            self._history.append(
                {
                    "at": iso_time(now),
                    "tracked": len(present),
                    "airborne": len(airborne),
                    "detections": len(detections),
                    "emergency": category_counts.get("emergency", 0),
                }
            )
            self._events.extend(emitted)
            return emitted

    def _log_detection_transition(self, track: FlightTrack, emitted: list[dict[str, Any]], now: datetime) -> None:
        is_detection = track.score >= self.detection_threshold
        was_detection = track.hex_id in self._open_detections
        if is_detection and not was_detection:
            self._open_detections.add(track.hex_id)
            top = max(track.triggers, key=lambda t: t.weight) if track.triggers else None
            emitted.append(
                self._event(
                    f"detection-opened:{track.dominant_category}",
                    track,
                    now,
                    top.message if top else f"{track.identity()} flagged",
                )
            )
        elif not is_detection and was_detection:
            self._open_detections.discard(track.hex_id)
            emitted.append(self._event("detection-cleared", track, now, f"{track.identity()} no longer flagged"))

    async def add_system_event(self, event_type: str, message: str) -> dict[str, Any]:
        async with self._lock:
            event = {
                "type": event_type,
                "hex": "system",
                "identity": "SkyVeil",
                "message": message,
                "category": None,
                "at": iso_time(utc_now()),
            }
            self._events.append(event)
            return event

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            now = utc_now()
            flights = [t.to_dict(now) for t in self._flights.values()]
            flights.sort(key=lambda f: (f["score"], f["present"]), reverse=True)
            detections = [f for f in flights if f["score"] >= self.detection_threshold]
            category_counts = {category: 0 for category in CATEGORIES}
            for f in detections:
                if f["dominant_category"] in category_counts:
                    category_counts[f["dominant_category"]] += 1
            return {
                "generated_at": iso_time(now),
                "detection_threshold": self.detection_threshold,
                "tracked_count": sum(1 for f in flights if f["present"]),
                "airborne_count": sum(1 for f in flights if f["present"] and not f["on_ground"]),
                "detection_count": len(detections),
                "category_counts": category_counts,
                "cloaked_count": sum(1 for f in flights if f["present"] and (f["is_pia"] or f["is_ladd"])),
                "military_count": sum(1 for f in flights if f["present"] and f["is_mil"]),
                "history": list(self._history),
                "flights": flights,
                "detections": detections[:250],
                "events": list(self._events),
            }

    def _event(self, event_type: str, track: FlightTrack, now: datetime, message: str) -> dict[str, Any]:
        return {
            "type": event_type,
            "hex": track.hex_id,
            "identity": track.identity(),
            "message": message,
            "category": track.dominant_category,
            "at": iso_time(now),
        }
