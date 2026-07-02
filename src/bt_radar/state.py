"""In-memory Bluetooth device state and movement tracking."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .anomaly import Finding, address_family, evaluate_device


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass
class Observation:
    address: str
    rssi: int
    name: str | None = None
    address_type: str | None = None
    manufacturer_id: int | None = None
    service_uuids: list[str] = field(default_factory=list)
    tx_power: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=utc_now)


@dataclass
class DeviceTrack:
    address: str
    first_seen: datetime
    last_seen: datetime
    name: str | None = None
    address_type: str | None = None
    manufacturer_id: int | None = None
    service_uuids: list[str] = field(default_factory=list)
    tx_power: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    seen_count: int = 0
    reappear_count: int = 0
    present: bool = True
    rssi_history: deque[int] = field(default_factory=lambda: deque(maxlen=80))
    time_history: deque[str] = field(default_factory=lambda: deque(maxlen=80))
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=40))
    findings: list[Finding] = field(default_factory=list)

    def update(self, observation: Observation, stale_after: float) -> list[dict[str, Any]]:
        emitted: list[dict[str, Any]] = []
        now = observation.observed_at

        if not self.present:
            self.reappear_count += 1
            self.present = True
            emitted.append(self._event("entered", now, "Device came back into range"))
        elif (now - self.last_seen).total_seconds() > stale_after:
            self.reappear_count += 1
            emitted.append(self._event("reappeared", now, "Device reappeared after a stale interval"))

        self.last_seen = now
        self.seen_count += 1
        self.name = observation.name or self.name
        self.address_type = observation.address_type or self.address_type
        self.manufacturer_id = observation.manufacturer_id if observation.manufacturer_id is not None else self.manufacturer_id
        self.service_uuids = observation.service_uuids or self.service_uuids
        self.tx_power = observation.tx_power if observation.tx_power is not None else self.tx_power
        self.details.update(observation.details)
        self.rssi_history.append(observation.rssi)
        self.time_history.append(iso_time(now))
        self.findings = evaluate_device(
            address=self.address,
            address_type=self.address_type,
            name=self.name,
            manufacturer_id=self.manufacturer_id,
            rssi_history=list(self.rssi_history),
            seen_count=self.seen_count,
            reappear_count=self.reappear_count,
            stale_seconds=0,
        )
        return emitted

    def mark_left_if_stale(self, now: datetime, stale_after: float) -> dict[str, Any] | None:
        if not self.present:
            return None
        if (now - self.last_seen).total_seconds() <= stale_after:
            return None
        self.present = False
        event = self._event("left", now, "Device is no longer being observed")
        self.findings = evaluate_device(
            address=self.address,
            address_type=self.address_type,
            name=self.name,
            manufacturer_id=self.manufacturer_id,
            rssi_history=list(self.rssi_history),
            seen_count=self.seen_count,
            reappear_count=self.reappear_count,
            stale_seconds=(now - self.last_seen).total_seconds(),
        )
        return event

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
        rssi_values = list(self.rssi_history)
        current_rssi = rssi_values[-1] if rssi_values else None
        smoothed_rssi = smooth_rssi(rssi_values)
        stale_seconds = (now - self.last_seen).total_seconds()
        estimated_distance_m = estimate_distance_meters(smoothed_rssi, self.tx_power)
        distance_label = estimate_distance_label(smoothed_rssi)
        movement = movement_label(rssi_values)
        findings = evaluate_device(
            address=self.address,
            address_type=self.address_type,
            name=self.name,
            manufacturer_id=self.manufacturer_id,
            rssi_history=rssi_values,
            seen_count=self.seen_count,
            reappear_count=self.reappear_count,
            stale_seconds=stale_seconds,
        )
        self.findings = findings
        return {
            "address": self.address,
            "address_family": address_family(self.address, self.address_type),
            "name": self.name,
            "address_type": self.address_type,
            "manufacturer_id": self.manufacturer_id,
            "manufacturer_hex": f"0x{self.manufacturer_id:04x}" if self.manufacturer_id is not None else None,
            "service_uuids": self.service_uuids,
            "tx_power": self.tx_power,
            "details": self.details,
            "first_seen": iso_time(self.first_seen),
            "last_seen": iso_time(self.last_seen),
            "stale_seconds": round(stale_seconds, 1),
            "seen_count": self.seen_count,
            "reappear_count": self.reappear_count,
            "present": self.present,
            "rssi": current_rssi,
            "rssi_smoothed": smoothed_rssi,
            "rssi_history": rssi_values,
            "time_history": list(self.time_history),
            "estimated_distance_m": estimated_distance_m,
            "distance_label": distance_label,
            "movement": movement,
            "findings": [asdict(finding) for finding in findings],
            "events": list(self.events),
        }


class RadarState:
    def __init__(self, stale_after: float = 20.0) -> None:
        self.stale_after = stale_after
        self._devices: dict[str, DeviceTrack] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._lock = asyncio.Lock()

    async def observe(self, observation: Observation) -> list[dict[str, Any]]:
        async with self._lock:
            track = self._devices.get(observation.address)
            emitted: list[dict[str, Any]]
            if track is None:
                track = DeviceTrack(
                    address=observation.address,
                    first_seen=observation.observed_at,
                    last_seen=observation.observed_at,
                    name=observation.name,
                    address_type=observation.address_type,
                    manufacturer_id=observation.manufacturer_id,
                    service_uuids=observation.service_uuids,
                    tx_power=observation.tx_power,
                    details=observation.details,
                    seen_count=1,
                )
                track.rssi_history.append(observation.rssi)
                track.time_history.append(iso_time(observation.observed_at))
                emitted = [track._event("new", observation.observed_at, "New Bluetooth device detected")]
                track.findings = evaluate_device(
                    address=track.address,
                    address_type=track.address_type,
                    name=track.name,
                    manufacturer_id=track.manufacturer_id,
                    rssi_history=list(track.rssi_history),
                    seen_count=track.seen_count,
                    reappear_count=track.reappear_count,
                    stale_seconds=0,
                )
                self._devices[track.address] = track
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
                for event in (track.mark_left_if_stale(now, self.stale_after) for track in self._devices.values())
                if event is not None
            ]
            self._events.extend(emitted)
            return emitted

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            now = utc_now()
            devices = [track.snapshot(now) for track in self._devices.values()]
            devices.sort(key=lambda item: (item["present"], item["rssi"] if item["rssi"] is not None else -999), reverse=True)
            return {
                "generated_at": iso_time(now),
                "device_count": len(devices),
                "present_count": sum(1 for item in devices if item["present"]),
                "devices": devices,
                "events": list(self._events),
            }

    async def add_system_event(self, event_type: str, message: str) -> dict[str, Any]:
        async with self._lock:
            event = {
                "type": event_type,
                "address": "system",
                "name": "Radar",
                "message": message,
                "at": iso_time(utc_now()),
            }
            self._events.append(event)
            return event


def movement_label(rssi_history: list[int]) -> str:
    if len(rssi_history) < 3:
        return "collecting"
    delta = rssi_history[-1] - rssi_history[max(0, len(rssi_history) - 6)]
    if delta >= 10:
        return "approaching"
    if delta <= -10:
        return "departing"
    return "steady"


def estimate_distance_label(rssi: int | None) -> str:
    if rssi is None:
        return "unknown"
    if rssi >= -50:
        return "very near"
    if rssi >= -65:
        return "near"
    if rssi >= -80:
        return "mid-range"
    return "far/weak"


def smooth_rssi(rssi_history: list[int], window: int = 6) -> int | None:
    if not rssi_history:
        return None
    tail = rssi_history[-window:]
    weighted_total = 0.0
    weight_sum = 0.0
    for index, rssi in enumerate(tail, start=1):
        weighted_total += rssi * index
        weight_sum += index
    return int(round(weighted_total / weight_sum))


def estimate_distance_meters(rssi: int | None, tx_power: int | None = None) -> float | None:
    """Approximate distance from RSSI using log-distance path loss.

    This is a coarse estimate and can vary substantially indoors.
    """
    if rssi is None:
        return None
    calibrated_tx_power = tx_power if tx_power is not None else -59
    path_loss_exponent = 2.2
    distance = 10 ** ((calibrated_tx_power - rssi) / (10 * path_loss_exponent))
    return round(max(0.2, min(distance, 80.0)), 2)
