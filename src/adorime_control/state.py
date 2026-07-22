"""In-memory device tracking and AdoRime control state."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import pstdev
from typing import Any

from .ble_stack import bleak_backend_label, host_platform
from .connection import DeviceConnectionManager
from .protocol import (
    classify_protocol,
    friendly_device_name,
    is_adorime_candidate,
    looks_like_galaku_code,
    match_reason,
    match_tier,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


@dataclass
class Observation:
    address: str
    rssi: int
    name: str | None = None
    address_type: str | None = None
    tx_power: int | None = None
    service_uuids: list[str] = field(default_factory=list)
    observed_at: datetime = field(default_factory=utc_now)
    ble_device: Any | None = None


@dataclass
class DeviceTrack:
    address: str
    first_seen: datetime
    last_seen: datetime
    name: str | None = None
    address_type: str | None = None
    tx_power: int | None = None
    service_uuids: list[str] = field(default_factory=list)
    seen_count: int = 0
    reappear_count: int = 0
    present: bool = True
    rssi_history: deque[int] = field(default_factory=lambda: deque(maxlen=120))
    time_history: deque[str] = field(default_factory=lambda: deque(maxlen=120))
    observed_history: deque[datetime] = field(default_factory=lambda: deque(maxlen=120))
    ble_device: Any | None = None

    def update(self, observation: Observation) -> None:
        self.last_seen = observation.observed_at
        self.seen_count += 1
        self.present = True
        self.name = observation.name or self.name
        self.address_type = observation.address_type or self.address_type
        self.tx_power = observation.tx_power if observation.tx_power is not None else self.tx_power
        if observation.service_uuids:
            merged = list(dict.fromkeys([*self.service_uuids, *observation.service_uuids]))
            self.service_uuids = merged
        if observation.ble_device is not None:
            self.ble_device = observation.ble_device
        self.rssi_history.append(observation.rssi)
        self.time_history.append(iso_time(observation.observed_at))
        self.observed_history.append(observation.observed_at)

    def mark_left_if_stale(self, now: datetime, stale_after: float) -> bool:
        if not self.present:
            return False
        if (now - self.last_seen).total_seconds() <= stale_after:
            return False
        self.present = False
        return True

    def snapshot(self, now: datetime) -> dict[str, Any]:
        rssi_values = list(self.rssi_history)
        current_rssi = rssi_values[-1] if rssi_values else None
        smoothed = smooth_rssi(rssi_values)
        protocol = classify_protocol(self.service_uuids, self.name)
        tier = match_tier(self.name, self.service_uuids)
        display_name = friendly_device_name(self.name) or self.name or "Unnamed BLE device"
        return {
            "address": self.address,
            "name": self.name,
            "display_name": display_name,
            "address_type": self.address_type,
            "tx_power": self.tx_power,
            "service_uuids": list(self.service_uuids),
            "protocol": protocol,
            "match_tier": tier,
            "match_reason": match_reason(self.name, self.service_uuids),
            "first_seen": iso_time(self.first_seen),
            "last_seen": iso_time(self.last_seen),
            "stale_seconds": round((now - self.last_seen).total_seconds(), 1),
            "seen_count": self.seen_count,
            "reappear_count": self.reappear_count,
            "present": self.present,
            "rssi": current_rssi,
            "rssi_smoothed": smoothed,
            "rssi_history": rssi_values,
            "time_history": list(self.time_history),
            "movement": movement_label(rssi_values),
            "adorime_candidate": tier in {"known", "probable"},
            "controllable": tier in {"known", "probable"},
        }


@dataclass
class ControlState:
    target_address: str | None = None
    mode: str = "manual"
    ai_enabled: bool = False
    ai_aggressiveness: float = 0.65
    min_thrust: int = 20
    max_thrust: int = 90
    last_command: dict[str, Any] | None = None
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=50))
    last_ai_command_at: datetime | None = None


class RadarState:
    def __init__(self, stale_after: float = 18.0) -> None:
        self.stale_after = stale_after
        self._devices: dict[str, DeviceTrack] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=240)
        self._control = ControlState()
        self._lock = asyncio.Lock()
        self.connections = DeviceConnectionManager()
        self.scan_mode = "live"
        self.scanner_error: str | None = None

    async def observe(self, observation: Observation) -> list[dict[str, Any]]:
        async with self._lock:
            track = self._devices.get(observation.address)
            emitted: list[dict[str, Any]] = []
            if track is None:
                track = DeviceTrack(
                    address=observation.address,
                    first_seen=observation.observed_at,
                    last_seen=observation.observed_at,
                    name=observation.name,
                    address_type=observation.address_type,
                    tx_power=observation.tx_power,
                    service_uuids=list(observation.service_uuids),
                    seen_count=1,
                    ble_device=observation.ble_device,
                )
                track.rssi_history.append(observation.rssi)
                track.time_history.append(iso_time(observation.observed_at))
                track.observed_history.append(observation.observed_at)
                self._devices[track.address] = track
                emitted.append(self._event("new", track, "New Bluetooth device detected", at=observation.observed_at))
            else:
                was_present = track.present
                track.update(observation)
                if not was_present:
                    track.reappear_count += 1
                    emitted.append(self._event("entered", track, "Device came back into range", at=observation.observed_at))

            ai_event = await self._maybe_emit_ai_command(observation.observed_at)
            if ai_event is not None:
                emitted.append(ai_event)

            self._events.extend(emitted)
            return emitted

    async def mark_stale(self) -> list[dict[str, Any]]:
        async with self._lock:
            now = utc_now()
            emitted: list[dict[str, Any]] = []
            for track in self._devices.values():
                if track.mark_left_if_stale(now, self.stale_after):
                    emitted.append(self._event("left", track, "Device is no longer being observed", at=now))

            idle_event = await self._emit_idle_command_if_target_missing(now)
            if idle_event is not None:
                emitted.append(idle_event)

            self._events.extend(emitted)
            return emitted

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            now = utc_now()
            devices: list[dict[str, Any]] = []
            for track in self._devices.values():
                payload = track.snapshot(now)
                methods = self._hiding_methods_for_track(track)
                payload["hiding_methods"] = methods
                payload["hiding_confidence"] = _max_confidence(methods)
                payload["gatt"] = self.connections.connection_snapshot(track.address)
                devices.append(payload)
            devices.sort(key=_device_sort_key, reverse=True)
            return {
                "generated_at": iso_time(now),
                "host_platform": host_platform(),
                "ble_backend": bleak_backend_label(),
                "scan_mode": self.scan_mode,
                "scanner_error": self.scanner_error,
                "device_count": len(devices),
                "present_count": sum(1 for item in devices if item["present"]),
                "candidate_count": sum(1 for item in devices if item.get("adorime_candidate")),
                "devices": devices,
                "control": self._control_payload(now),
                "events": list(self._events),
            }

    async def control_snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return self._control_payload(utc_now())

    async def set_scan_status(self, *, mode: str, error: str | None = None) -> dict[str, Any]:
        async with self._lock:
            self.scan_mode = mode
            self.scanner_error = error
            message = f"Scanner mode: {mode}" + (f" ({error})" if error else "")
            event = self._event("scanner-status", None, message, at=utc_now())
            self._events.append(event)
            return event

    async def set_control_target(self, address: str | None) -> dict[str, Any]:
        async with self._lock:
            if address is None:
                previous = self._control.target_address
                self._control.target_address = None
                self._control.ai_enabled = False
                if previous:
                    await self.connections.disconnect(previous)
                event = self._event("control-target", None, "Control target cleared", at=utc_now())
                self._events.append(event)
                return event

            track = self._devices.get(address)
            if track is None:
                raise ValueError(f"Unknown device address: {address}")
            tier = match_tier(track.name, track.service_uuids)
            if tier not in {"known", "probable"}:
                raise ValueError(
                    "Selected device does not look like an AdoRime/Galaku toy "
                    "(need a known code, Galaku service UUID, or short opaque BLE name)."
                )

            if self._control.target_address and self._control.target_address != address:
                await self.connections.disconnect(self._control.target_address)

            self._control.target_address = address
            self._control.last_ai_command_at = None
            label = friendly_device_name(track.name) or track.name or track.address
            event = self._event(
                "control-target",
                track,
                f"Control target set to {label}",
                at=utc_now(),
            )
            self._events.append(event)
            return event

    async def connect_target(self) -> dict[str, Any]:
        async with self._lock:
            track = self._require_target()
            try:
                gatt = await self.connections.connect(
                    address=track.address,
                    name=track.name,
                    service_uuids=track.service_uuids,
                    ble_device=track.ble_device,
                )
            except Exception as exc:
                event = self._event(
                    "control-connect-error",
                    track,
                    f"GATT connect failed: {type(exc).__name__}: {exc}",
                    at=utc_now(),
                )
                self._events.append(event)
                raise
            event = self._event(
                "control-connect",
                track,
                f"Connected over GATT ({gatt.get('protocol')})",
                at=utc_now(),
            )
            self._events.append(event)
            return event

    async def disconnect_target(self) -> dict[str, Any]:
        async with self._lock:
            track = self._require_target()
            await self.connections.disconnect(track.address)
            event = self._event("control-disconnect", track, "Disconnected GATT session", at=utc_now())
            self._events.append(event)
            return event

    async def send_manual_thrust(self, thrust: int, pattern: str = "steady") -> dict[str, Any]:
        async with self._lock:
            track = self._require_target()
            level = clamp_int(int(thrust), 0, 100)
            self._control.mode = "manual"
            self._control.ai_enabled = False
            wire = await self._write_thrust(track, level, pattern)
            event = self._record_command(
                track=track,
                source="manual",
                thrust=level,
                pattern=_normalize_pattern(pattern),
                reason="Manual thrust override",
                at=utc_now(),
                wire=wire,
            )
            self._events.append(event)
            return event

    async def configure_ai_thrust(
        self,
        *,
        enabled: bool,
        aggressiveness: float,
        min_thrust: int,
        max_thrust: int,
    ) -> dict[str, Any]:
        async with self._lock:
            self._require_target()
            min_level = clamp_int(int(min_thrust), 0, 100)
            max_level = clamp_int(int(max_thrust), 0, 100)
            if min_level > max_level:
                raise ValueError("min_thrust must be less than or equal to max_thrust")

            self._control.mode = "ai-thrust"
            self._control.ai_enabled = bool(enabled)
            self._control.ai_aggressiveness = max(0.0, min(float(aggressiveness), 1.0))
            self._control.min_thrust = min_level
            self._control.max_thrust = max_level
            self._control.last_ai_command_at = None

            target = self._devices.get(self._control.target_address or "")
            message = (
                f"AI thrust {'enabled' if self._control.ai_enabled else 'disabled'} "
                f"(aggressiveness {self._control.ai_aggressiveness:.2f}, "
                f"range {min_level}-{max_level})"
            )
            event = self._event("control-ai", target, message, at=utc_now())
            self._events.append(event)
            return event

    async def run_ai_thrust_step(self) -> dict[str, Any]:
        async with self._lock:
            if not self._control.ai_enabled:
                raise ValueError("AI thrust mode is disabled")
            event = await self._maybe_emit_ai_command(utc_now(), force=True)
            if event is None:
                raise ValueError("Unable to produce AI thrust command")
            self._events.append(event)
            return event

    async def add_system_event(self, event_type: str, message: str) -> dict[str, Any]:
        async with self._lock:
            event = self._event(event_type, None, message, at=utc_now())
            self._events.append(event)
            return event

    def _control_payload(self, now: datetime) -> dict[str, Any]:
        target = self._devices.get(self._control.target_address or "")
        nearby = [track.snapshot(now) for track in self._devices.values()]
        nearby.sort(key=_device_sort_key, reverse=True)
        supported = [item for item in nearby if item.get("controllable")]
        ai_preview = self._predict_ai_command(target) if target is not None else None
        fleet_assessment = self._fleet_hiding_assessment()
        gatt = self.connections.connection_snapshot(self._control.target_address)
        return {
            "target_address": self._control.target_address,
            "target_name": (friendly_device_name(target.name) or target.name) if target else None,
            "target_present": target.present if target else False,
            "mode": self._control.mode,
            "ai_enabled": self._control.ai_enabled,
            "ai_aggressiveness": round(self._control.ai_aggressiveness, 2),
            "min_thrust": self._control.min_thrust,
            "max_thrust": self._control.max_thrust,
            "gatt": gatt,
            "nearby_devices": [
                {
                    "address": item["address"],
                    "name": item["name"],
                    "display_name": item["display_name"],
                    "present": item["present"],
                    "rssi": item["rssi"],
                    "protocol": item["protocol"],
                    "match_tier": item["match_tier"],
                    "match_reason": item["match_reason"],
                    "adorime_candidate": item["adorime_candidate"],
                    "controllable": item["controllable"],
                    "gatt": self.connections.connection_snapshot(item["address"]),
                    "hiding_methods": self._hiding_methods_for_address(item["address"]),
                    "hiding_confidence": _max_confidence(self._hiding_methods_for_address(item["address"])),
                }
                for item in nearby
            ],
            "supported_devices": [
                {
                    "address": item["address"],
                    "name": item["name"],
                    "display_name": item["display_name"],
                    "present": item["present"],
                    "rssi": item["rssi"],
                    "protocol": item["protocol"],
                    "match_tier": item["match_tier"],
                    "match_reason": item["match_reason"],
                    "gatt": self.connections.connection_snapshot(item["address"]),
                    "hiding_methods": self._hiding_methods_for_address(item["address"]),
                    "hiding_confidence": _max_confidence(self._hiding_methods_for_address(item["address"])),
                }
                for item in supported
            ],
            "hiding_assessment": fleet_assessment,
            "ai_preview": ai_preview,
            "last_command": self._control.last_command,
            "history": list(self._control.history),
        }

    async def _maybe_emit_ai_command(self, now: datetime, *, force: bool = False) -> dict[str, Any] | None:
        if not self._control.ai_enabled:
            return None
        if not force and self._control.last_ai_command_at is not None:
            elapsed = (now - self._control.last_ai_command_at).total_seconds()
            if elapsed < 1.0:
                return None
        try:
            track = self._require_target(present_required=True)
        except ValueError:
            return None
        prediction = self._predict_ai_command(track)
        if prediction is None:
            return None
        self._control.last_ai_command_at = now
        wire = await self._write_thrust(track, prediction["thrust"], prediction["pattern"])
        return self._record_command(
            track=track,
            source="ai-thrust",
            thrust=prediction["thrust"],
            pattern=prediction["pattern"],
            reason=prediction["reason"],
            at=now,
            wire=wire,
        )

    async def _emit_idle_command_if_target_missing(self, now: datetime) -> dict[str, Any] | None:
        if not self._control.ai_enabled:
            return None
        target = self._devices.get(self._control.target_address or "")
        if target is None or target.present:
            return None
        last_command = self._control.last_command or {}
        if int(last_command.get("thrust", -1)) == 0:
            return None
        wire = await self._write_thrust(target, 0, "idle")
        return self._record_command(
            track=target,
            source="ai-thrust",
            thrust=0,
            pattern="idle",
            reason="Target out of range",
            at=now,
            wire=wire,
        )

    async def _write_thrust(self, track: DeviceTrack, thrust: int, pattern: str) -> dict[str, Any] | None:
        if self.scan_mode == "demo":
            return {
                "mode": "demo",
                "address": track.address,
                "thrust": thrust,
                "pattern": pattern,
                "note": "Demo mode: command recorded locally only (no GATT write).",
            }
        if not self.connections.is_connected(track.address):
            # Auto-connect like the AdoRime app before sending the first command.
            await self.connections.connect(
                address=track.address,
                name=track.name,
                service_uuids=track.service_uuids,
                ble_device=track.ble_device,
            )
        return await self.connections.send_thrust(track.address, thrust, pattern=pattern)

    def _predict_ai_command(self, track: DeviceTrack) -> dict[str, Any] | None:
        if not track.present:
            return {"thrust": 0, "pattern": "idle", "reason": "Target out of range"}

        rssi_values = list(track.rssi_history)
        smoothed = smooth_rssi(rssi_values)
        if smoothed is None:
            return None

        near_score = max(0.0, min((smoothed + 92) / 50.0, 1.0))
        recent = rssi_values[-10:]
        volatility_db = pstdev(recent) if len(recent) >= 2 else 0.0
        volatility_score = max(0.0, min(volatility_db / 14.0, 1.0))
        movement = movement_label(rssi_values)
        movement_boost = 0.12 if movement == "approaching" else (-0.10 if movement == "departing" else 0.0)

        score = (
            0.45 * near_score
            + 0.35 * self._control.ai_aggressiveness
            + 0.20 * volatility_score
            + movement_boost
        )
        score = max(0.0, min(score, 1.0))
        thrust = round(self._control.min_thrust + score * (self._control.max_thrust - self._control.min_thrust))

        pattern = "steady"
        if movement == "approaching":
            pattern = "ramp"
        if volatility_score >= 0.65:
            pattern = "pulse"
        reason = f"RSSI {smoothed} dBm, movement {movement}, volatility {volatility_db:.1f} dB"
        return {"thrust": clamp_int(thrust, 0, 100), "pattern": pattern, "reason": reason}

    def _record_command(
        self,
        *,
        track: DeviceTrack,
        source: str,
        thrust: int,
        pattern: str,
        reason: str,
        at: datetime,
        wire: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        command = {
            "at": iso_time(at),
            "source": source,
            "mode": self._control.mode,
            "address": track.address,
            "name": friendly_device_name(track.name) or track.name,
            "thrust": clamp_int(thrust, 0, 100),
            "pattern": pattern,
            "reason": reason,
            "wire": wire,
        }
        self._control.last_command = command
        self._control.history.append(command)
        return {
            "type": "control-command",
            "address": track.address,
            "name": command["name"],
            "message": f"{source} thrust {command['thrust']}% ({pattern})",
            "at": command["at"],
            "control": command,
        }

    def _require_target(self, *, present_required: bool = False) -> DeviceTrack:
        address = self._control.target_address
        if not address:
            raise ValueError("No control target selected")
        track = self._devices.get(address)
        if track is None:
            raise ValueError(f"Target {address} is not known")
        if present_required and not track.present:
            raise ValueError(f"Target {address} is not currently in range")
        return track

    def _hiding_methods_for_address(self, address: str) -> list[dict[str, Any]]:
        track = self._devices.get(address)
        if track is None:
            return []
        return self._hiding_methods_for_track(track)

    def _hiding_methods_for_track(self, track: DeviceTrack) -> list[dict[str, Any]]:
        methods: list[dict[str, Any]] = []
        randomized = _uses_private_address(track.address, track.address_type)
        if randomized:
            methods.append(
                {
                    "method": "private-address-randomization",
                    "confidence": "high" if track.address_type == "random" else "medium",
                    "summary": "Uses BLE random/private addressing to reduce stable tracking.",
                    "evidence": f"address_type={track.address_type or 'unknown'}, address={track.address}",
                }
            )

        gaps = _observation_gaps_seconds(track.observed_history)
        if gaps:
            threshold = max(2.5, self.stale_after * 0.45)
            long_gap_count = sum(1 for gap in gaps if gap >= threshold)
            ratio = long_gap_count / len(gaps)
            max_gap = max(gaps)
            if ratio >= 0.30 or max_gap >= self.stale_after * 0.9:
                methods.append(
                    {
                        "method": "low-duty-cycle-advertising",
                        "confidence": "high" if max_gap >= self.stale_after else "medium",
                        "summary": "Broadcast windows appear sparse/intermittent, reducing discoverability.",
                        "evidence": f"max_gap={max_gap:.1f}s, long_gap_ratio={ratio:.2f}",
                    }
                )

        if track.name is None or not track.name.strip():
            methods.append(
                {
                    "method": "identity-suppression",
                    "confidence": "medium",
                    "summary": "No stable advertised name, making attribution harder.",
                    "evidence": "device name missing in advertisements",
                }
            )
        elif looks_like_galaku_code(track.name) or (track.name or "").upper() in {
            "QD48",
            "BGSF",
            "BGQS",
            "AX05",
            "DT01",
            "BGZY",
            "A531",
            "SN80",
            "BGCD",
            "YXSJ",
        }:
            methods.append(
                {
                    "method": "opaque-local-name",
                    "confidence": "high",
                    "summary": "Advertises a short opaque product code instead of the AdoRime brand name.",
                    "evidence": f"local_name={track.name}",
                }
            )

        return methods

    def _fleet_hiding_assessment(self) -> dict[str, Any]:
        adorime_tracks = [
            track for track in self._devices.values() if is_adorime_candidate(track.name, track.service_uuids)
        ]
        findings = [(track, self._hiding_methods_for_track(track)) for track in adorime_tracks]
        flat_methods = [entry["method"] for _, methods in findings for entry in methods]
        confidence = _max_confidence([entry for _, methods in findings for entry in methods])
        method_counts: dict[str, int] = {}
        for method in flat_methods:
            method_counts[method] = method_counts.get(method, 0) + 1
        primary_methods = [name for name, _ in sorted(method_counts.items(), key=lambda item: item[1], reverse=True)[:3]]
        return {
            "confidence": confidence,
            "primary_methods": primary_methods,
            "evaluated_devices": len(adorime_tracks),
            "note": (
                "Heuristic estimate from observed BLE traffic only. "
                "AdoRime toys typically hide as short Galaku-family codes (e.g. BGSF/QD48), not 'Adorime'."
            ),
        }

    @staticmethod
    def _event(event_type: str, track: DeviceTrack | None, message: str, *, at: datetime) -> dict[str, Any]:
        return {
            "type": event_type,
            "address": track.address if track else "system",
            "name": (friendly_device_name(track.name) or track.name) if track else "Control",
            "message": message,
            "at": iso_time(at),
        }


def movement_label(rssi_history: list[int]) -> str:
    if len(rssi_history) < 3:
        return "collecting"
    delta = rssi_history[-1] - rssi_history[max(0, len(rssi_history) - 6)]
    if delta >= 10:
        return "approaching"
    if delta <= -10:
        return "departing"
    return "steady"


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


def _observation_gaps_seconds(history: deque[datetime]) -> list[float]:
    if len(history) < 2:
        return []
    values = list(history)
    return [max(0.0, (values[index] - values[index - 1]).total_seconds()) for index in range(1, len(values))]


def _uses_private_address(address: str, address_type: str | None) -> bool:
    if (address_type or "").strip().lower() == "random":
        return True
    parts = address.split(":")
    if len(parts) != 6:
        return False
    try:
        first_octet = int(parts[0], 16)
    except ValueError:
        return False
    return (first_octet & 0b1100_0000) == 0b1100_0000


def _max_confidence(methods: list[dict[str, Any]]) -> str:
    if not methods:
        return "low"
    ranking = {"low": 0, "medium": 1, "high": 2}
    best = "low"
    for method in methods:
        confidence = str(method.get("confidence", "low")).lower()
        if ranking.get(confidence, 0) > ranking[best]:
            best = confidence
    return best


def _normalize_pattern(pattern: str) -> str:
    normalized = pattern.strip().lower()
    if not normalized:
        return "steady"
    return normalized[:24]


_MATCH_TIER_RANK = {"known": 3, "probable": 2, "none": 0}


def _device_sort_key(item: dict[str, Any]) -> tuple:
    return (
        bool(item.get("present")),
        _MATCH_TIER_RANK.get(str(item.get("match_tier") or "none"), 0),
        item["rssi"] if item.get("rssi") is not None else -999,
    )
