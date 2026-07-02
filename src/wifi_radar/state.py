"""In-memory WiFi device state, motion tracking and proximity alarms."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .motion import (
    classify_motion,
    distance_label,
    estimate_distance_meters,
    movement_direction,
    smooth_rssi,
)

# Distance must climb back above range * this factor before a device that is
# already inside the alarm zone is considered to have left it. The hysteresis
# stops a device hovering near the boundary from re-triggering repeatedly.
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


class RadarState:
    def __init__(self, stale_after: float = 20.0, alarm_range_m: float = 5.0) -> None:
        self.stale_after = stale_after
        self.alarm_range_m = alarm_range_m
        self._devices: dict[str, DeviceTrack] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._lock = asyncio.Lock()

    async def observe(self, observation: Observation) -> list[dict[str, Any]]:
        async with self._lock:
            track = self._devices.get(observation.bssid)
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
                self._devices[track.bssid] = track
                emitted.append(self._event("new", track, observation.observed_at, "New WiFi device detected"))
            else:
                was_present = track.present
                track.update(observation)
                if not was_present:
                    emitted.append(self._event("entered", track, observation.observed_at, "Device came back into range"))

            emitted.extend(self._evaluate_alarm(track, observation.observed_at))
            self._events.extend(emitted)
            return emitted

    async def mark_stale(self) -> list[dict[str, Any]]:
        async with self._lock:
            now = utc_now()
            emitted: list[dict[str, Any]] = []
            for track in self._devices.values():
                if track.mark_left_if_stale(now, self.stale_after):
                    emitted.append(self._event("left", track, now, "Device is no longer being observed"))
            self._events.extend(emitted)
            return emitted

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
                    track,
                    now,
                    f"Device within {distance:.1f} m (alarm range {self.alarm_range_m:.1f} m), motion: {track.motion()}",
                    alarm=True,
                )
            )
        elif track.in_alarm_zone and distance > self.alarm_range_m * ALARM_RELEASE_FACTOR:
            track.in_alarm_zone = False
            emitted.append(
                self._event(
                    "alarm-clear",
                    track,
                    now,
                    f"Device moved out to {distance:.1f} m",
                )
            )
        return emitted

    async def set_alarm_range(self, alarm_range_m: float) -> dict[str, Any]:
        async with self._lock:
            alarm_range_m = max(0.5, min(float(alarm_range_m), 120.0))
            self.alarm_range_m = alarm_range_m
            for track in self._devices.values():
                track.in_alarm_zone = False
            return self._event(
                "config",
                None,
                utc_now(),
                f"Alarm range set to {alarm_range_m:.1f} m",
            )

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            now = utc_now()
            devices = [track.snapshot(now) for track in self._devices.values()]
            devices.sort(
                key=lambda item: (item["present"], item["rssi"] if item["rssi"] is not None else -999),
                reverse=True,
            )
            return {
                "generated_at": iso_time(now),
                "alarm_range_m": self.alarm_range_m,
                "device_count": len(devices),
                "present_count": sum(1 for item in devices if item["present"]),
                "stationary_count": sum(1 for item in devices if item["present"] and item["motion"] == "stationary"),
                "moving_count": sum(1 for item in devices if item["present"] and item["motion"] == "moving"),
                "alarm_count": sum(1 for item in devices if item["in_alarm_zone"]),
                "devices": devices,
                "events": list(self._events),
            }

    async def add_system_event(self, event_type: str, message: str) -> dict[str, Any]:
        async with self._lock:
            event = self._event(event_type, None, utc_now(), message)
            self._events.append(event)
            return event

    def _event(
        self,
        event_type: str,
        track: DeviceTrack | None,
        at: datetime,
        message: str,
        *,
        alarm: bool = False,
    ) -> dict[str, Any]:
        return {
            "type": event_type,
            "bssid": track.bssid if track else "system",
            "ssid": track.ssid if track else "Radar",
            "message": message,
            "alarm": alarm,
            "at": iso_time(at),
        }
