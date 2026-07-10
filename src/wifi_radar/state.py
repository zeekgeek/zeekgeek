"""In-memory WiFi AP/client state, motion tracking and proximity alarms."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .analysis import build_ai_analysis
from .motion import classify_motion, distance_label, estimate_distance_meters, movement_direction, smooth_rssi

ALARM_RELEASE_FACTOR = 1.2


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass
class Observation:
    bssid: str
    rssi: int
    ssid: str | None = None
    channel: int | None = None
    frequency_mhz: int | None = None
    vendor: str | None = None
    observed_at: datetime = field(default_factory=utc_now)


@dataclass
class ClientObservation:
    mac: str
    associated_bssid: str | None = None
    rssi: int | None = None
    frame_type: str = "data"
    probe_ssid: str | None = None
    observed_at: datetime = field(default_factory=utc_now)


@dataclass
class DeviceTrack:
    bssid: str
    first_seen: datetime
    last_seen: datetime
    ssid: str | None = None
    channel: int | None = None
    frequency_mhz: int | None = None
    vendor: str | None = None
    seen_count: int = 0
    present: bool = True
    in_alarm_zone: bool = False
    rssi_history: deque[int] = field(default_factory=lambda: deque(maxlen=120))
    time_history: deque[str] = field(default_factory=lambda: deque(maxlen=120))

    def update(self, observation: Observation) -> None:
        self.last_seen = observation.observed_at
        self.seen_count += 1
        self.present = True
        self.ssid = observation.ssid or self.ssid
        self.channel = observation.channel if observation.channel is not None else self.channel
        self.frequency_mhz = observation.frequency_mhz if observation.frequency_mhz is not None else self.frequency_mhz
        self.vendor = observation.vendor or self.vendor
        self.rssi_history.append(observation.rssi)
        self.time_history.append(iso_time(observation.observed_at))

    def mark_left_if_stale(self, now: datetime, stale_after: float) -> bool:
        if not self.present:
            return False
        if (now - self.last_seen).total_seconds() <= stale_after:
            return False
        self.present = False
        self.in_alarm_zone = False
        return True

    def estimated_distance(self) -> float | None:
        return estimate_distance_meters(smooth_rssi(list(self.rssi_history)))

    def motion(self) -> str:
        return classify_motion(list(self.rssi_history))

    def snapshot(self, now: datetime) -> dict[str, Any]:
        rssi_values = list(self.rssi_history)
        current_rssi = rssi_values[-1] if rssi_values else None
        smoothed = smooth_rssi(rssi_values)
        distance = estimate_distance_meters(smoothed)
        return {
            "bssid": self.bssid,
            "ssid": self.ssid,
            "channel": self.channel,
            "frequency_mhz": self.frequency_mhz,
            "vendor": self.vendor,
            "first_seen": iso_time(self.first_seen),
            "last_seen": iso_time(self.last_seen),
            "stale_seconds": round((now - self.last_seen).total_seconds(), 1),
            "seen_count": self.seen_count,
            "present": self.present,
            "in_alarm_zone": self.in_alarm_zone,
            "rssi": current_rssi,
            "rssi_smoothed": smoothed,
            "rssi_history": rssi_values,
            "time_history": list(self.time_history),
            "estimated_distance_m": distance,
            "distance_label": distance_label(distance),
            "motion": self.motion(),
            "direction": movement_direction(rssi_values),
        }


@dataclass
class ClientTrack:
    mac: str
    first_seen: datetime
    last_seen: datetime
    associated_bssid: str | None = None
    seen_count: int = 0
    probe_count: int = 0
    frame_count: int = 0
    present: bool = True
    rssi_history: deque[int] = field(default_factory=lambda: deque(maxlen=120))
    time_history: deque[str] = field(default_factory=lambda: deque(maxlen=120))
    probe_ssids: deque[str] = field(default_factory=lambda: deque(maxlen=20))
    frame_types: deque[str] = field(default_factory=lambda: deque(maxlen=40))

    def update(self, observation: ClientObservation) -> None:
        self.last_seen = observation.observed_at
        self.present = True
        self.seen_count += 1
        self.frame_count += 1
        if observation.associated_bssid is not None:
            self.associated_bssid = observation.associated_bssid
        if observation.frame_type == "probe-request":
            self.probe_count += 1
        if observation.probe_ssid:
            self.probe_ssids.append(observation.probe_ssid)
        self.frame_types.append(observation.frame_type)
        if observation.rssi is not None:
            self.rssi_history.append(observation.rssi)
        self.time_history.append(iso_time(observation.observed_at))

    def mark_left_if_stale(self, now: datetime, stale_after: float) -> bool:
        if not self.present:
            return False
        if (now - self.last_seen).total_seconds() <= stale_after:
            return False
        self.present = False
        return True

    def snapshot(self, now: datetime) -> dict[str, Any]:
        rssi_values = list(self.rssi_history)
        motion = classify_motion(rssi_values) if rssi_values else "collecting"
        direction = movement_direction(rssi_values) if rssi_values else "steady"
        smoothed = smooth_rssi(rssi_values)
        return {
            "mac": self.mac,
            "associated_bssid": self.associated_bssid,
            "first_seen": iso_time(self.first_seen),
            "last_seen": iso_time(self.last_seen),
            "stale_seconds": round((now - self.last_seen).total_seconds(), 1),
            "seen_count": self.seen_count,
            "frame_count": self.frame_count,
            "probe_count": self.probe_count,
            "present": self.present,
            "rssi": rssi_values[-1] if rssi_values else None,
            "rssi_smoothed": smoothed,
            "motion": motion,
            "direction": direction,
            "probe_ssids": list(dict.fromkeys(self.probe_ssids)),
            "recent_frame_types": list(self.frame_types),
        }


class RadarState:
    def __init__(self, stale_after: float = 20.0, alarm_range_m: float = 5.0) -> None:
        self.stale_after = stale_after
        self.alarm_range_m = alarm_range_m
        self._aps: dict[str, DeviceTrack] = {}
        self._clients: dict[str, ClientTrack] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=240)
        self._lock = asyncio.Lock()
        self._monitor_status = {
            "enabled": False,
            "base_interface": None,
            "monitor_interface": None,
            "note": "Monitor mode disabled.",
        }

    async def observe(self, observation: Observation) -> list[dict[str, Any]]:
        async with self._lock:
            track = self._aps.get(observation.bssid)
            emitted: list[dict[str, Any]] = []
            if track is None:
                track = DeviceTrack(
                    bssid=observation.bssid,
                    first_seen=observation.observed_at,
                    last_seen=observation.observed_at,
                    ssid=observation.ssid,
                    channel=observation.channel,
                    frequency_mhz=observation.frequency_mhz,
                    vendor=observation.vendor,
                    seen_count=1,
                )
                track.rssi_history.append(observation.rssi)
                track.time_history.append(iso_time(observation.observed_at))
                self._aps[track.bssid] = track
                emitted.append(self._event("new-ap", observation.observed_at, "New WiFi AP detected", bssid=track.bssid, ssid=track.ssid))
            else:
                was_present = track.present
                track.update(observation)
                if not was_present:
                    emitted.append(
                        self._event(
                            "entered-ap",
                            observation.observed_at,
                            "WiFi AP came back into range",
                            bssid=track.bssid,
                            ssid=track.ssid,
                        )
                    )
            emitted.extend(self._evaluate_alarm(track, observation.observed_at))
            self._events.extend(emitted)
            return emitted

    async def observe_client(self, observation: ClientObservation) -> list[dict[str, Any]]:
        async with self._lock:
            track = self._clients.get(observation.mac)
            emitted: list[dict[str, Any]] = []
            if track is None:
                track = ClientTrack(
                    mac=observation.mac,
                    first_seen=observation.observed_at,
                    last_seen=observation.observed_at,
                    associated_bssid=observation.associated_bssid,
                )
                self._clients[track.mac] = track
                emitted.append(
                    self._event(
                        "new-client",
                        observation.observed_at,
                        "New WiFi client detected",
                        mac=track.mac,
                        bssid=track.associated_bssid,
                    )
                )
            track.update(observation)
            self._events.extend(emitted)
            return emitted

    async def mark_stale(self) -> list[dict[str, Any]]:
        async with self._lock:
            now = utc_now()
            emitted: list[dict[str, Any]] = []
            for track in self._aps.values():
                if track.mark_left_if_stale(now, self.stale_after):
                    emitted.append(self._event("left-ap", now, "WiFi AP is no longer being observed", bssid=track.bssid, ssid=track.ssid))
            for track in self._clients.values():
                if track.mark_left_if_stale(now, self.stale_after):
                    emitted.append(
                        self._event(
                            "left-client",
                            now,
                            "WiFi client is no longer being observed",
                            mac=track.mac,
                            bssid=track.associated_bssid,
                        )
                    )
            self._events.extend(emitted)
            return emitted

    async def set_alarm_range(self, alarm_range_m: float) -> dict[str, Any]:
        async with self._lock:
            alarm_range_m = max(0.5, min(float(alarm_range_m), 120.0))
            self.alarm_range_m = alarm_range_m
            for track in self._aps.values():
                track.in_alarm_zone = False
            event = self._event("config", utc_now(), f"Alarm range set to {alarm_range_m:.1f} m")
            self._events.append(event)
            return event

    async def set_monitor_status(
        self,
        *,
        enabled: bool,
        base_interface: str | None,
        monitor_interface: str | None,
        note: str,
    ) -> dict[str, Any]:
        async with self._lock:
            self._monitor_status = {
                "enabled": enabled,
                "base_interface": base_interface,
                "monitor_interface": monitor_interface,
                "note": note,
            }
            event = self._event("monitor-mode", utc_now(), note, bssid=monitor_interface)
            self._events.append(event)
            return event

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            now = utc_now()
            aps = [track.snapshot(now) for track in self._aps.values()]
            clients = [track.snapshot(now) for track in self._clients.values()]
            aps.sort(key=lambda item: (item["present"], item["rssi"] if item["rssi"] is not None else -999), reverse=True)
            clients.sort(
                key=lambda item: (item["present"], item["frame_count"], item["rssi"] if item["rssi"] is not None else -999),
                reverse=True,
            )

            alarm_count = sum(1 for item in aps if item["in_alarm_zone"])
            analysis = build_ai_analysis(
                aps=aps,
                clients=clients,
                alarm_count=alarm_count,
                monitor_mode_enabled=bool(self._monitor_status.get("enabled")),
            )
            return {
                "generated_at": iso_time(now),
                "alarm_range_m": self.alarm_range_m,
                "device_count": len(aps),
                "present_count": sum(1 for item in aps if item["present"]),
                "stationary_count": sum(1 for item in aps if item["present"] and item["motion"] == "stationary"),
                "moving_count": sum(1 for item in aps if item["present"] and item["motion"] == "moving"),
                "alarm_count": alarm_count,
                "client_count": len(clients),
                "client_present_count": sum(1 for item in clients if item["present"]),
                "clients_associated_count": sum(1 for item in clients if item["present"] and item["associated_bssid"]),
                "monitor_mode": dict(self._monitor_status),
                "devices": aps,
                "aps": aps,
                "clients": clients,
                "ai_analysis": analysis,
                "events": list(self._events),
            }

    async def add_system_event(self, event_type: str, message: str) -> dict[str, Any]:
        async with self._lock:
            event = self._event(event_type, utc_now(), message)
            self._events.append(event)
            return event

    def _evaluate_alarm(self, track: DeviceTrack, now: datetime) -> list[dict[str, Any]]:
        distance = track.estimated_distance()
        if distance is None:
            return []
        emitted: list[dict[str, Any]] = []
        if not track.in_alarm_zone and distance <= self.alarm_range_m:
            track.in_alarm_zone = True
            emitted.append(
                self._event(
                    "alarm",
                    now,
                    f"AP within {distance:.1f} m (alarm range {self.alarm_range_m:.1f} m), motion: {track.motion()}",
                    bssid=track.bssid,
                    ssid=track.ssid,
                    alarm=True,
                )
            )
        elif track.in_alarm_zone and distance > self.alarm_range_m * ALARM_RELEASE_FACTOR:
            track.in_alarm_zone = False
            emitted.append(
                self._event(
                    "alarm-clear",
                    now,
                    f"AP moved out to {distance:.1f} m",
                    bssid=track.bssid,
                    ssid=track.ssid,
                )
            )
        return emitted

    @staticmethod
    def _event(
        event_type: str,
        at: datetime,
        message: str,
        *,
        bssid: str | None = None,
        mac: str | None = None,
        ssid: str | None = None,
        alarm: bool = False,
    ) -> dict[str, Any]:
        return {
            "type": event_type,
            "bssid": bssid or "system",
            "mac": mac,
            "ssid": ssid or ("Client" if mac else (bssid or "Radar")),
            "message": message,
            "alarm": alarm,
            "at": iso_time(at),
        }
