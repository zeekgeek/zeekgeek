"""In-memory toy scanner and controller state."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from bt_radar.anomaly import Finding, address_family, evaluate_device
from bt_radar.calibration import estimate_distance_label, estimate_distance_meters
from bt_radar.state import movement_label, smooth_rssi

from .protocols import (
    DeviceProfile,
    catalog_patterns,
    catalog_quick_levels,
    catalog_thrust_modes,
    catalog_vibrate_modes,
    match_adorime_profile,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass
class ToyObservation:
    address: str
    name: str | None
    rssi: int
    address_type: str | None = None
    service_uuids: list[str] = field(default_factory=list)
    manufacturer_id: int | None = None
    tx_power: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=utc_now)


@dataclass
class ToyTrack:
    address: str
    first_seen: datetime
    last_seen: datetime
    name: str | None = None
    address_type: str | None = None
    rssi: int = -127
    rssi_history: deque[int] = field(default_factory=lambda: deque(maxlen=80))
    time_history: deque[str] = field(default_factory=lambda: deque(maxlen=80))
    service_uuids: list[str] = field(default_factory=list)
    manufacturer_id: int | None = None
    tx_power: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    seen_count: int = 0
    reappear_count: int = 0
    present: bool = True
    profile: DeviceProfile | None = None
    connected: bool = False
    levels: dict[str, int] = field(default_factory=dict)
    active_pattern: str | None = None
    battery_percent: int | None = None
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=40))
    findings: list[Finding] = field(default_factory=list)

    def update(self, observation: ToyObservation, stale_after: float) -> list[dict[str, Any]]:
        emitted: list[dict[str, Any]] = []
        now = observation.observed_at

        if not self.present:
            self.reappear_count += 1
            self.present = True
            emitted.append(self._event("entered", now, "Toy came back into range"))
        elif (now - self.last_seen).total_seconds() > stale_after:
            self.reappear_count += 1
            emitted.append(self._event("reappeared", now, "Toy reappeared after a stale interval"))

        self.last_seen = now
        self.seen_count += 1
        self.name = observation.name or self.name
        self.address_type = observation.address_type or self.address_type
        self.rssi = observation.rssi
        self.rssi_history.append(observation.rssi)
        self.time_history.append(iso_time(now))
        self.service_uuids = observation.service_uuids or self.service_uuids
        self.manufacturer_id = observation.manufacturer_id if observation.manufacturer_id is not None else self.manufacturer_id
        self.tx_power = observation.tx_power if observation.tx_power is not None else self.tx_power
        self.details.update(observation.details)
        self.profile = match_adorime_profile(self.name)
        if self.profile and not self.levels:
            self.levels = {motor.id: 0 for motor in self.profile.motors}
        self._refresh_findings(stale_seconds=0)
        return emitted

    def mark_left_if_stale(self, now: datetime, stale_after: float) -> dict[str, Any] | None:
        if not self.present:
            return None
        if (now - self.last_seen).total_seconds() <= stale_after:
            return None
        self.present = False
        if self.connected:
            self.connected = False
            self.active_pattern = None
            self.levels = {key: 0 for key in self.levels}
        stale_seconds = (now - self.last_seen).total_seconds()
        self._refresh_findings(stale_seconds=stale_seconds)
        return self._event("left", now, "Toy is no longer being observed")

    def set_connection(self, connected: bool, at: datetime | None = None) -> dict[str, Any]:
        now = at or utc_now()
        self.connected = connected
        if not connected:
            self.active_pattern = None
            self.levels = {key: 0 for key in self.levels}
            return self._event("disconnected", now, "Disconnected from toy")
        return self._event("connected", now, "Connected to toy")

    def set_levels(self, levels: dict[str, int], pattern: str | None = None) -> None:
        self.levels.update({key: max(0, min(100, int(value))) for key, value in levels.items()})
        self.active_pattern = pattern

    def _refresh_findings(self, stale_seconds: float) -> None:
        self.findings = evaluate_device(
            address=self.address,
            address_type=self.address_type,
            name=self.name,
            manufacturer_id=self.manufacturer_id,
            rssi_history=list(self.rssi_history),
            seen_count=self.seen_count,
            reappear_count=self.reappear_count,
            stale_seconds=stale_seconds,
        )

    def _event(self, event_type: str, at: datetime, message: str) -> dict[str, Any]:
        event = {
            "type": event_type,
            "address": self.address,
            "name": self.name,
            "message": message,
            "at": iso_time(at),
        }
        self.events.append(event)
        return event

    def snapshot(self, now: datetime) -> dict[str, Any]:
        profile = self.profile
        rssi_values = list(self.rssi_history)
        current_rssi = rssi_values[-1] if rssi_values else None
        smoothed_rssi = smooth_rssi(rssi_values)
        stale_seconds = (now - self.last_seen).total_seconds()
        estimated_distance_m = estimate_distance_meters(smoothed_rssi, self.tx_power)
        self._refresh_findings(stale_seconds=stale_seconds)
        return {
            "address": self.address,
            "name": self.name,
            "display_name": profile.name if profile else (self.name or "Unknown toy"),
            "brand": profile.brand if profile else "unknown",
            "theme": profile.theme if profile else "classic",
            "protocol": profile.protocol if profile else None,
            "controllable": profile is not None,
            "motors": profile.to_dict()["motors"] if profile else [],
            "address_family": address_family(self.address, self.address_type),
            "address_type": self.address_type,
            "manufacturer_id": self.manufacturer_id,
            "manufacturer_hex": f"0x{self.manufacturer_id:04x}" if self.manufacturer_id is not None else None,
            "tx_power": self.tx_power,
            "details": self.details,
            "rssi": current_rssi,
            "rssi_smoothed": smoothed_rssi,
            "rssi_history": rssi_values,
            "time_history": list(self.time_history),
            "estimated_distance_m": estimated_distance_m,
            "distance_label": estimate_distance_label(estimated_distance_m),
            "movement": movement_label(rssi_values),
            "seen_count": self.seen_count,
            "reappear_count": self.reappear_count,
            "service_uuids": self.service_uuids,
            "present": self.present,
            "connected": self.connected,
            "levels": dict(self.levels),
            "active_pattern": self.active_pattern,
            "battery_percent": self.battery_percent,
            "findings": [asdict(finding) for finding in self.findings],
            "events": list(self.events),
            "first_seen": iso_time(self.first_seen),
            "last_seen": iso_time(self.last_seen),
            "stale_seconds": round(stale_seconds, 1),
        }


class ControllerState:
    def __init__(self, stale_after: float = 20.0) -> None:
        self.stale_after = stale_after
        self._toys: dict[str, ToyTrack] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._selected_address: str | None = None
        self._lock = asyncio.Lock()

    async def observe(self, observation: ToyObservation) -> list[dict[str, Any]]:
        async with self._lock:
            track = self._toys.get(observation.address)
            emitted: list[dict[str, Any]]
            if track is None:
                profile = match_adorime_profile(observation.name)
                if profile is None:
                    return []
                track = ToyTrack(
                    address=observation.address,
                    first_seen=observation.observed_at,
                    last_seen=observation.observed_at,
                    name=observation.name,
                    address_type=observation.address_type,
                    rssi=observation.rssi,
                    service_uuids=observation.service_uuids,
                    manufacturer_id=observation.manufacturer_id,
                    tx_power=observation.tx_power,
                    details=observation.details,
                    profile=profile,
                    seen_count=1,
                    levels={motor.id: 0 for motor in profile.motors} if profile else {},
                )
                track.rssi_history.append(observation.rssi)
                track.time_history.append(iso_time(observation.observed_at))
                emitted = [track._event("new", observation.observed_at, "Compatible toy discovered")]
                track._refresh_findings(stale_seconds=0)
                self._toys[track.address] = track
                if self._selected_address is None and profile is not None:
                    self._selected_address = track.address
            else:
                emitted = track.update(observation, self.stale_after)

            for event in emitted:
                self._events.append(event)
            return emitted

    async def mark_stale(self) -> list[dict[str, Any]]:
        async with self._lock:
            now = utc_now()
            emitted = [
                event
                for event in (track.mark_left_if_stale(now, self.stale_after) for track in self._toys.values())
                if event is not None
            ]
            self._events.extend(emitted)
            return emitted

    async def select(self, address: str | None) -> None:
        async with self._lock:
            self._selected_address = address

    async def set_connection(self, address: str, connected: bool) -> dict[str, Any] | None:
        async with self._lock:
            track = self._toys.get(address)
            if track is None:
                return None
            event = track.set_connection(connected)
            self._events.append(event)
            return event

    async def set_levels(
        self,
        address: str,
        levels: dict[str, int],
        *,
        pattern: str | None = None,
    ) -> dict[str, Any] | None:
        async with self._lock:
            track = self._toys.get(address)
            if track is None:
                return None
            track.set_levels(levels, pattern=pattern)
            event = {
                "type": "control",
                "address": address,
                "name": track.name,
                "message": f"Updated control levels: {track.levels}",
                "at": iso_time(utc_now()),
            }
            self._events.append(event)
            return event

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            now = utc_now()
            toys = [track.snapshot(now) for track in self._toys.values()]
            toys.sort(
                key=lambda item: (
                    item["present"],
                    item["connected"],
                    item["controllable"],
                    item["rssi"] if item["rssi"] is not None else -999,
                ),
                reverse=True,
            )
            return {
                "generated_at": iso_time(now),
                "scanner_mode": "live",
                "toy_count": len(toys),
                "present_count": sum(1 for item in toys if item["present"]),
                "connected_count": sum(1 for item in toys if item["connected"]),
                "controllable_count": sum(1 for item in toys if item["controllable"]),
                "selected_address": self._selected_address,
                "patterns": catalog_patterns(),
                "thrust_modes": catalog_thrust_modes(),
                "vibrate_modes": catalog_vibrate_modes(),
                "quick_levels": catalog_quick_levels(),
                "toys": toys,
                "events": list(self._events),
            }

    async def get_track(self, address: str) -> ToyTrack | None:
        async with self._lock:
            return self._toys.get(address)

    async def add_system_event(self, event_type: str, message: str) -> dict[str, Any]:
        async with self._lock:
            event = {
                "type": event_type,
                "address": "system",
                "name": "Controller",
                "message": message,
                "at": iso_time(utc_now()),
            }
            self._events.append(event)
            return event
