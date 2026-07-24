"""In-memory jet tracks, movement history, and strange-event alarm state."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .anomaly import (
    DEFAULT_SIGMA,
    DEFAULT_TRIGGER_THRESHOLD,
    STRANGE_SQUAWKS,
    MovementBaseline,
    StrangeEventAlarm,
    TrackSnapshot,
    evaluate_triggers,
    movement_posture,
)
from .watchlist import match_watchlist, nearest_privacy_destination, PRIVACY_DESTINATIONS


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass
class JetObservation:
    hex_id: str
    callsign: str | None = None
    registration: str | None = None
    type_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    altitude_ft: int | None = None
    ground_speed_kt: float | None = None
    track_deg: float | None = None
    squawk: str | None = None
    on_ground: bool = False
    is_tanker: bool = False
    observed_at: datetime = field(default_factory=utc_now)


@dataclass
class JetTrack:
    hex_id: str
    first_seen: datetime
    last_seen: datetime
    callsign: str | None = None
    registration: str | None = None
    type_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    altitude_ft: int | None = None
    ground_speed_kt: float | None = None
    track_deg: float | None = None
    previous_track_deg: float | None = None
    previous_altitude_ft: int | None = None
    squawk: str | None = None
    on_ground: bool = False
    is_tanker: bool = False
    present: bool = True
    seen_count: int = 0
    watched_label: str | None = None
    watched_notes: str | None = None
    movement_style: str | None = None
    airborne_flags: deque[bool] = field(default_factory=lambda: deque(maxlen=48))
    altitude_history: deque[int | None] = field(default_factory=lambda: deque(maxlen=120))
    time_history: deque[str] = field(default_factory=lambda: deque(maxlen=120))
    privacy_visits: Counter = field(default_factory=Counter)

    def update(self, obs: JetObservation) -> None:
        self.previous_track_deg = self.track_deg
        self.previous_altitude_ft = self.altitude_ft
        self.last_seen = obs.observed_at
        self.seen_count += 1
        self.present = True
        self.callsign = obs.callsign or self.callsign
        self.registration = obs.registration or self.registration
        self.type_code = obs.type_code or self.type_code
        self.is_tanker = obs.is_tanker or self.is_tanker
        if obs.lat is not None:
            self.lat = obs.lat
        if obs.lon is not None:
            self.lon = obs.lon
        self.altitude_ft = obs.altitude_ft
        self.ground_speed_kt = obs.ground_speed_kt
        self.track_deg = obs.track_deg
        self.squawk = obs.squawk
        self.on_ground = obs.on_ground
        self.altitude_history.append(obs.altitude_ft)
        self.time_history.append(iso_time(obs.observed_at))
        self.airborne_flags.append(not obs.on_ground)
        watched = match_watchlist(self.registration, self.callsign)
        if watched:
            self.watched_label = watched.label
            self.watched_notes = watched.notes
            self.movement_style = watched.movement_style

    def identity(self) -> str:
        if self.watched_label:
            return f"{(self.callsign or self.registration or self.hex_id)} [{self.watched_label}]"
        return (self.callsign or "").strip() or self.registration or self.hex_id

    def mark_left_if_stale(self, now: datetime, stale_after: float) -> bool:
        if not self.present:
            return False
        if (now - self.last_seen).total_seconds() <= stale_after:
            return False
        self.present = False
        return True

    def snapshot(self, now: datetime, *, include_history: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "hex": self.hex_id,
            "callsign": (self.callsign or "").strip() or None,
            "registration": self.registration,
            "type": self.type_code,
            "identity": self.identity(),
            "lat": self.lat,
            "lon": self.lon,
            "altitude_ft": self.altitude_ft,
            "ground_speed_kt": self.ground_speed_kt,
            "track_deg": self.track_deg,
            "squawk": self.squawk,
            "emergency_squawk": self.squawk in STRANGE_SQUAWKS,
            "on_ground": self.on_ground,
            "airborne": self.present and not self.on_ground,
            "dark": self.present and not (self.callsign or "").strip() and not self.is_tanker,
            "is_tanker": self.is_tanker,
            "present": self.present,
            "seen_count": self.seen_count,
            "watched_label": self.watched_label,
            "watched_notes": self.watched_notes,
            "movement_style": self.movement_style,
            "posture": movement_posture(list(self.airborne_flags)),
            "first_seen": iso_time(self.first_seen),
            "last_seen": iso_time(self.last_seen),
            "stale_seconds": round((now - self.last_seen).total_seconds(), 1),
        }
        if include_history:
            data["privacy_visits"] = dict(self.privacy_visits)
            data["altitude_history"] = list(self.altitude_history)
            data["time_history"] = list(self.time_history)
        return data


class RadarState:
    """Tracks jets across poll cycles and raises the strange-event alarm."""

    def __init__(
        self,
        *,
        stale_after: float = 120.0,
        sigma: float = DEFAULT_SIGMA,
        trigger_threshold: int = DEFAULT_TRIGGER_THRESHOLD,
        baseline_window: int = 240,
        min_baseline_samples: int = 10,
        cycle_seconds: float = 60.0,
    ) -> None:
        self.stale_after = stale_after
        self.sigma = sigma
        self.cycle_seconds = cycle_seconds
        self._jets: dict[str, JetTrack] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=400)
        self._history: deque[dict[str, Any]] = deque(maxlen=360)
        self._hideout_hits: Counter[str] = Counter()
        self._hideout_notes: dict[str, str] = {}
        self._watchlist_moves: deque[dict[str, Any]] = deque(maxlen=80)
        self._baseline = MovementBaseline(window=baseline_window, min_samples=min_baseline_samples)
        self._alarm = StrangeEventAlarm(threshold=trigger_threshold)
        self._alarmed_squawks: set[str] = set()
        self._privacy_alerted: set[str] = set()
        self._last_cycle: dict[str, Any] = {}
        self.scan_mode: str = "starting"
        self.awaiting_first_poll: bool = True
        self._lock = asyncio.Lock()

    async def set_scan_status(self, *, mode: str, awaiting_first_poll: bool | None = None) -> None:
        async with self._lock:
            self.scan_mode = mode
            if awaiting_first_poll is not None:
                self.awaiting_first_poll = awaiting_first_poll

    async def ingest_cycle(self, observations: list[JetObservation]) -> list[dict[str, Any]]:
        async with self._lock:
            now = utc_now()
            emitted: list[dict[str, Any]] = []
            previously_airborne = {
                hex_id for hex_id, track in self._jets.items() if track.present and not track.on_ground
            }
            previously_present = {hex_id for hex_id, track in self._jets.items() if track.present}

            for obs in observations:
                track = self._jets.get(obs.hex_id)
                if track is None:
                    track = JetTrack(
                        hex_id=obs.hex_id,
                        first_seen=obs.observed_at,
                        last_seen=obs.observed_at,
                    )
                    self._jets[obs.hex_id] = track
                    track.update(obs)
                    if not obs.on_ground and not obs.is_tanker:
                        emitted.append(self._event("new-jet", track, now, f"{track.identity()} appeared airborne"))
                else:
                    was_airborne = track.present and not track.on_ground
                    track.update(obs)
                    if not was_airborne and not obs.on_ground and not obs.is_tanker:
                        emitted.append(self._event("took-off", track, now, f"{track.identity()} is now airborne"))
                        if track.watched_label:
                            self._watchlist_moves.append(
                                {
                                    "at": iso_time(now),
                                    "identity": track.identity(),
                                    "label": track.watched_label,
                                    "style": track.movement_style,
                                    "action": "departed",
                                }
                            )

            left_tracks: list[JetTrack] = []
            for track in self._jets.values():
                if track.hex_id in previously_present and track.mark_left_if_stale(now, self.stale_after):
                    left_tracks.append(track)
                    emitted.append(self._event("left", track, now, f"{track.identity()} left ADS-B coverage"))

            privacy_landings: list[tuple[str, str]] = []
            for track in left_tracks:
                if track.lat is None or track.lon is None:
                    continue
                match = nearest_privacy_destination(track.lat, track.lon)
                if match is None:
                    continue
                dest, distance = match
                track.privacy_visits[dest.name] += 1
                self._hideout_hits[dest.name] += 1
                self._hideout_notes[dest.name] = dest.notes
                key = f"{track.hex_id}:{dest.code}"
                if track.watched_label and key not in self._privacy_alerted:
                    self._privacy_alerted.add(key)
                    privacy_landings.append((track.identity(), f"{dest.name} ({distance:.0f} nm)"))
                    if track.watched_label:
                        self._watchlist_moves.append(
                            {
                                "at": iso_time(now),
                                "identity": track.identity(),
                                "label": track.watched_label,
                                "style": track.movement_style,
                                "action": f"quiet near {dest.name}",
                            }
                        )

            airborne_tracks = [
                t for t in self._jets.values() if t.present and not t.on_ground and not t.is_tanker
            ]
            airborne = len(airborne_tracks)
            new_airborne = sum(1 for t in airborne_tracks if t.hex_id not in previously_airborne)
            dark_flights = sum(1 for t in airborne_tracks if not (t.callsign or "").strip())

            emergency: list[tuple[str, str]] = []
            for track in airborne_tracks:
                if track.squawk in STRANGE_SQUAWKS and track.hex_id not in self._alarmed_squawks:
                    self._alarmed_squawks.add(track.hex_id)
                    emergency.append((track.identity(), track.squawk or ""))
                elif track.squawk not in STRANGE_SQUAWKS:
                    self._alarmed_squawks.discard(track.hex_id)

            snapshots = [
                TrackSnapshot(
                    hex_id=t.hex_id,
                    identity=t.identity(),
                    registration=t.registration,
                    lat=t.lat,
                    lon=t.lon,
                    altitude_ft=t.altitude_ft,
                    ground_speed_kt=t.ground_speed_kt,
                    track_deg=t.track_deg,
                    previous_track_deg=t.previous_track_deg,
                    previous_altitude_ft=t.previous_altitude_ft,
                    cycle_seconds=self.cycle_seconds,
                    watched_label=t.watched_label,
                    movement_style=t.movement_style,
                    just_became_airborne=t.hex_id not in previously_airborne and t.present and not t.on_ground,
                    just_went_quiet=False,
                    is_tanker=t.is_tanker,
                )
                for t in self._jets.values()
                if t.present
            ]

            airborne_z, departures_z = self._baseline.score(airborne, new_airborne)
            triggers = evaluate_triggers(
                airborne=airborne,
                new_airborne=new_airborne,
                airborne_z=airborne_z,
                departures_z=departures_z,
                emergency_squawks=emergency,
                dark_flights=dark_flights,
                sigma=self.sigma,
                tracks=snapshots,
                privacy_landings=privacy_landings,
            )
            self._baseline.record(airborne, new_airborne)

            for trigger in triggers:
                emitted.append(self._system_event(f"trigger:{trigger.code}", trigger.detail, at=now))

            transition = self._alarm.update(len(triggers))
            if transition == "fired":
                emitted.append(
                    self._system_event(
                        "strange-event-alarm",
                        f"STRANGE EVENT: {self._alarm.recent_triggers} movement triggers in the recent window "
                        f"(threshold {self._alarm.threshold}). {airborne} jets airborne.",
                        alarm=True,
                        at=now,
                    )
                )
            elif transition == "cleared":
                emitted.append(
                    self._system_event("alarm-cleared", "Movement triggers quieted down; alarm cleared.", at=now)
                )

            self._history.append(
                {
                    "at": iso_time(now),
                    "airborne": airborne,
                    "new_airborne": new_airborne,
                    "dark": dark_flights,
                    "airborne_z": airborne_z,
                    "triggers": len(triggers),
                    "alarm": self._alarm.active,
                    "watched_airborne": sum(1 for t in airborne_tracks if t.watched_label),
                }
            )
            self._last_cycle = {
                "at": iso_time(now),
                "airborne": airborne,
                "new_airborne": new_airborne,
                "dark_flights": dark_flights,
                "airborne_z": airborne_z,
                "departures_z": departures_z,
                "triggers": [
                    {"code": t.code, "detail": t.detail, "score": t.score} for t in triggers
                ],
            }
            self.awaiting_first_poll = False
            self._prune_old_tracks(now)
            self._events.extend(emitted)
            return emitted

    def _prune_old_tracks(self, now: datetime) -> None:
        """Drop jets that left coverage long ago so live snapshots stay browser-sized."""
        cutoff = self.stale_after * 3
        stale_hexes = [
            hex_id
            for hex_id, track in self._jets.items()
            if not track.present and (now - track.last_seen).total_seconds() > cutoff
        ]
        for hex_id in stale_hexes:
            del self._jets[hex_id]

    async def set_sensitivity(
        self, *, sigma: float | None = None, trigger_threshold: int | None = None
    ) -> dict[str, Any]:
        async with self._lock:
            if sigma is not None:
                self.sigma = max(1.0, min(float(sigma), 8.0))
            if trigger_threshold is not None:
                self._alarm.threshold = max(1, min(int(trigger_threshold), 20))
            event = self._system_event(
                "config",
                f"Sensitivity set: sigma {self.sigma:.1f}, trigger threshold {self._alarm.threshold}",
            )
            self._events.append(event)
            return event

    async def add_system_event(self, event_type: str, message: str) -> dict[str, Any]:
        async with self._lock:
            event = self._system_event(event_type, message)
            self._events.append(event)
            return event

    async def snapshot(self, *, stream: bool = False) -> dict[str, Any]:
        async with self._lock:
            now = utc_now()
            include_history = not stream
            jets = [track.snapshot(now, include_history=include_history) for track in self._jets.values()]
            jets.sort(
                key=lambda item: (
                    bool(item["watched_label"]),
                    item["present"],
                    item["emergency_squawk"],
                    item["altitude_ft"] if item["altitude_ft"] is not None else -1,
                ),
                reverse=True,
            )
            if stream:
                present = [jet for jet in jets if jet["present"]]
                gone = [jet for jet in jets if not jet["present"]]
                jets = present[:180] + gone[:20]
            else:
                jets = jets[:250]
            hideouts = [
                {
                    "name": name,
                    "hits": hits,
                    "notes": self._hideout_notes.get(name, ""),
                }
                for name, hits in self._hideout_hits.most_common(12)
            ]
            posture_summary: dict[str, list[str]] = defaultdict(list)
            for jet in jets:
                if jet["watched_label"] and jet["present"]:
                    posture_summary[jet["posture"]].append(jet["identity"])
            return {
                "generated_at": iso_time(now),
                "scan_mode": self.scan_mode,
                "awaiting_first_poll": self.awaiting_first_poll,
                "feed_source": "adsb.lol" if self.scan_mode == "live" else ("simulated" if self.scan_mode == "demo" else "unknown"),
                "data_is_live": self.scan_mode == "live" and not self.awaiting_first_poll,
                "alarm_active": self._alarm.active,
                "recent_triggers": self._alarm.recent_triggers,
                "trigger_threshold": self._alarm.threshold,
                "sigma": self.sigma,
                "baseline": self._baseline.stats(),
                "last_cycle": self._last_cycle,
                "jet_count": len(jets),
                "airborne_count": sum(1 for j in jets if j["airborne"]),
                "dark_count": sum(1 for j in jets if j["dark"] and j["airborne"]),
                "emergency_count": sum(1 for j in jets if j["emergency_squawk"] and j["present"]),
                "watched_count": sum(1 for j in jets if j["watched_label"] and j["present"]),
                "tanker_count": sum(1 for j in jets if j["is_tanker"] and j["present"]),
                "history": list(self._history),
                "hideout_candidates": hideouts,
                "watchlist_moves": list(self._watchlist_moves),
                "posture_summary": {key: values for key, values in posture_summary.items()},
                "privacy_regions": [
                    {
                        "code": dest.code,
                        "name": dest.name,
                        "lat": dest.lat,
                        "lon": dest.lon,
                        "radius_nm": dest.radius_nm,
                        "notes": dest.notes,
                    }
                    for dest in PRIVACY_DESTINATIONS
                ],
                "jets": jets,
                "events": list(self._events),
            }

    def _event(self, event_type: str, track: JetTrack, at: datetime, message: str) -> dict[str, Any]:
        return {
            "type": event_type,
            "hex": track.hex_id,
            "identity": track.identity(),
            "message": message,
            "alarm": False,
            "at": iso_time(at),
        }

    def _system_event(
        self, event_type: str, message: str, *, alarm: bool = False, at: datetime | None = None
    ) -> dict[str, Any]:
        return {
            "type": event_type,
            "hex": "system",
            "identity": "Jet Radar",
            "message": message,
            "alarm": alarm,
            "at": iso_time(at or utc_now()),
        }
