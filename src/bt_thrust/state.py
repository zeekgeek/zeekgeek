"""In-memory toy scanner and controller state."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
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
    has_galaku_service,
    protocol_config,
    resolve_device_profile,
)
from .signal_quality import device_type_label, rssi_stats


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
    ble_device: Any = None
    source: str = "live"


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
    manufacturer_data: list[dict[str, Any]] = field(default_factory=list)
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
    gatt_services: list[dict[str, Any]] = field(default_factory=list)
    gatt_error: str | None = None
    transport: str = "ble"
    device_class: str | None = None
    ble_device: Any = None
    data_source: str = "live"
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
        if observation.details.get("manufacturer_data"):
            self.manufacturer_data = list(observation.details["manufacturer_data"])
        self.tx_power = observation.tx_power if observation.tx_power is not None else self.tx_power
        self.details.update(observation.details)
        if observation.ble_device is not None:
            self.ble_device = observation.ble_device
        if observation.source:
            self.data_source = observation.source
        local_name = observation.details.get("local_name")
        self.profile = resolve_device_profile(
            self.name,
            service_uuids=self.service_uuids,
            local_name=local_name if isinstance(local_name, str) else None,
        )
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
        local_name = self.details.get("local_name")
        control_uuids: dict[str, str] = {}
        if profile is not None:
            config = protocol_config(profile.protocol)
            control_uuids = {
                "service_uuid": config["service_uuid"],
                "tx_uuid": config["tx_uuid"],
            }
        signal_stats = rssi_stats(rssi_values)
        device_type = device_type_label(
            controllable=profile is not None,
            adorime_match=profile is not None and profile.brand == "adorime",
            galaku_service=has_galaku_service(self.service_uuids),
            name=self.name,
        )
        return {
            "address": self.address,
            "name": self.name,
            "local_name": local_name if isinstance(local_name, str) else None,
            "display_name": profile.name if profile else (self.name or self.address),
            "brand": profile.brand if profile else "unknown",
            "theme": profile.theme if profile else "classic",
            "protocol": profile.protocol if profile else None,
            "controllable": profile is not None,
            "adorime_match": profile is not None and profile.brand == "adorime",
            "galaku_service": has_galaku_service(self.service_uuids),
            "device_type": device_type,
            "transport": self.transport,
            "device_class": self.device_class,
            "data_source": self.data_source,
            "signal_stats": signal_stats,
            "signal_quality": signal_stats["quality"],
            "gatt_services": list(self.gatt_services),
            "gatt_error": self.gatt_error,
            "motors": profile.to_dict()["motors"] if profile else [],
            "address_family": address_family(self.address, self.address_type),
            "address_type": self.address_type,
            "manufacturer_id": self.manufacturer_id,
            "manufacturer_hex": f"0x{self.manufacturer_id:04x}" if self.manufacturer_id is not None else None,
            "manufacturer_data": list(self.manufacturer_data),
            "tx_power": self.tx_power,
            "is_connectable": self.details.get("is_connectable"),
            "control_uuids": control_uuids,
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
        self._scanner_paused = False
        self._scanner_active = False
        self._scanner_error: str | None = None
        self._scanner_mode: str = "off"
        self._adapter_probe: dict[str, Any] | None = None
        self._observation_count = 0
        self._last_observation_at: datetime | None = None
        self._deep_scan_until: datetime | None = None
        self._deep_scan_task: asyncio.Task | None = None
        self._min_rssi_filter: int = -127
        self._device_type_filter: str = "all"
        self._lock = asyncio.Lock()

    async def is_scanner_paused(self) -> bool:
        async with self._lock:
            return self._scanner_paused

    async def set_adapter_probe(self, probe: dict[str, Any] | None) -> None:
        async with self._lock:
            self._adapter_probe = probe

    async def set_scanner_active(self, active: bool, *, error: str | None = None, mode: str | None = None) -> None:
        async with self._lock:
            self._scanner_active = active
            self._scanner_error = error
            if mode is not None:
                self._scanner_mode = mode
            elif not active and error:
                self._scanner_mode = "off"

    def _deep_scan_active(self, now: datetime) -> bool:
        return self._deep_scan_until is not None and now < self._deep_scan_until

    async def set_scanner_paused(self, paused: bool) -> dict[str, Any]:
        async with self._lock:
            self._scanner_paused = paused
            if paused:
                self._deep_scan_until = None
            event = {
                "type": "scanner-paused" if paused else "scanner-resumed",
                "address": "system",
                "name": "Scanner",
                "message": "Scanner paused" if paused else "Scanner resumed",
                "at": iso_time(utc_now()),
            }
            self._events.append(event)
            return event

    async def trigger_deep_scan(self, duration_seconds: float = 20.0) -> dict[str, Any]:
        async with self._lock:
            duration = max(5.0, min(120.0, float(duration_seconds)))
            now = utc_now()
            self._scanner_paused = False
            self._deep_scan_until = now + timedelta(seconds=duration)
            event = {
                "type": "scanner-deep-scan",
                "address": "system",
                "name": "Scanner",
                "message": f"Deep scan enabled for {int(duration)}s",
                "at": iso_time(now),
            }
            self._events.append(event)
            return event

    async def set_scanner_filters(
        self,
        *,
        min_rssi: int | None = None,
        device_type: str | None = None,
    ) -> None:
        async with self._lock:
            if min_rssi is not None:
                parsed = int(min_rssi)
                # -127 (or out-of-range values) means "show all devices"
                self._min_rssi_filter = parsed if -100 <= parsed <= -30 else -127
            if device_type is not None:
                self._device_type_filter = device_type

    async def store_gatt_result(self, address: str, result: dict[str, Any]) -> dict[str, Any] | None:
        async with self._lock:
            track = self._toys.get(address)
            if track is None:
                return None
            track.gatt_services = list(result.get("services") or [])
            track.gatt_error = result.get("error")
            event = {
                "type": "gatt-deep-scan",
                "address": address,
                "name": track.name,
                "message": (
                    f"GATT deep scan complete ({len(track.gatt_services)} services)"
                    if not track.gatt_error
                    else f"GATT deep scan failed: {track.gatt_error}"
                ),
                "at": iso_time(utc_now()),
            }
            track.events.append(event)
            self._events.append(event)
            return event

    async def observe_classic_device(
        self,
        *,
        address: str,
        name: str,
        device_class: str | None = None,
        rssi: int | None = None,
    ) -> None:
        async with self._lock:
            now = utc_now()
            track = self._toys.get(address)
            if track is None:
                track = ToyTrack(
                    address=address,
                    first_seen=now,
                    last_seen=now,
                    name=name,
                    transport="classic",
                    device_class=device_class,
                    seen_count=1,
                )
                if rssi is not None:
                    track.rssi = rssi
                    track.rssi_history.append(rssi)
                    track.time_history.append(iso_time(now))
                self._toys[address] = track
                self._events.append(track._event("new", now, "Classic Bluetooth device discovered"))
            else:
                track.present = True
                track.last_seen = now
                track.name = name or track.name
                track.transport = "classic"
                track.device_class = device_class or track.device_class
                if rssi is not None:
                    track.rssi = rssi
                    track.rssi_history.append(rssi)
                    track.time_history.append(iso_time(now))

    async def set_stale_after(self, stale_after: float) -> None:
        async with self._lock:
            self.stale_after = max(3.0, min(120.0, float(stale_after)))

    async def clear_stale_devices(self) -> int:
        async with self._lock:
            removable = [
                address
                for address, track in self._toys.items()
                if not track.present and not track.connected
            ]
            for address in removable:
                del self._toys[address]
            if removable:
                event = {
                    "type": "scanner-clear",
                    "address": "system",
                    "name": "Scanner",
                    "message": f"Cleared {len(removable)} stale device(s) from the list",
                    "at": iso_time(utc_now()),
                }
                self._events.append(event)
            return len(removable)

    async def observe(self, observation: ToyObservation) -> list[dict[str, Any]]:
        async with self._lock:
            if self._scanner_paused:
                return []

            self._observation_count += 1
            self._last_observation_at = observation.observed_at
            local_name = observation.details.get("local_name")
            local_name_str = local_name if isinstance(local_name, str) else None
            profile = resolve_device_profile(
                observation.name,
                service_uuids=observation.service_uuids,
                local_name=local_name_str,
            )

            track = self._toys.get(observation.address)
            emitted: list[dict[str, Any]]
            if track is None:
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
                    details=dict(observation.details),
                    profile=profile,
                    ble_device=observation.ble_device,
                    data_source=observation.source,
                    seen_count=1,
                    levels={motor.id: 0 for motor in profile.motors} if profile else {},
                )
                if observation.details.get("manufacturer_data"):
                    track.manufacturer_data = list(observation.details["manufacturer_data"])
                track.rssi_history.append(observation.rssi)
                track.time_history.append(iso_time(observation.observed_at))
                if profile is not None:
                    message = "Adorime-compatible device discovered"
                else:
                    message = "Bluetooth device discovered"
                emitted = [track._event("new", observation.observed_at, message)]
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
            all_toys = [track.snapshot(now) for track in self._toys.values()]
            toys = list(all_toys)
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
                "scanner_mode": self._scanner_mode,
                "scanner": {
                    "active": self._scanner_active,
                    "paused": self._scanner_paused,
                    "error": self._scanner_error,
                    "mode": self._scanner_mode,
                    "deep_scan_active": self._deep_scan_active(now),
                    "deep_scan_until": iso_time(self._deep_scan_until)
                    if self._deep_scan_until
                    else None,
                    "observation_count": self._observation_count,
                    "last_observation_at": iso_time(self._last_observation_at)
                    if self._last_observation_at
                    else None,
                    "stale_after": self.stale_after,
                    "min_rssi_filter": self._min_rssi_filter,
                    "device_type_filter": self._device_type_filter,
                    "adapter_probe": self._adapter_probe,
                    "live_data": self._scanner_mode == "live",
                },
                "device_count": len(all_toys),
                "toy_count": len(all_toys),
                "present_count": sum(1 for item in all_toys if item["present"]),
                "connected_count": sum(1 for item in all_toys if item["connected"]),
                "controllable_count": sum(1 for item in all_toys if item["controllable"]),
                "adorime_count": sum(1 for item in all_toys if item["adorime_match"]),
                "filtered_count": len(
                    [
                        item
                        for item in all_toys
                        if self._passes_scanner_filters(item)
                    ]
                ),
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

    async def get_ble_device(self, address: str) -> Any:
        async with self._lock:
            track = self._toys.get(address)
            return track.ble_device if track is not None else None

    def _passes_scanner_filters(self, toy: dict[str, Any]) -> bool:
        if self._min_rssi_filter > -127:
            rssi = toy.get("rssi")
            if rssi is not None and rssi < self._min_rssi_filter:
                return False
        if self._device_type_filter != "all" and toy.get("device_type") != self._device_type_filter:
            return False
        return True

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
