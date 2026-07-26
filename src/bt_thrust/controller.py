"""Live toy connection and GATT command backend."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .ai_assist import ThrusterAdvisor
from .protocols import (
    DeviceProfile,
    build_command,
    levels_from_pattern,
    pattern_steps,
    protocol_config,
    resolve_device_profile,
)
from .state import ControllerState

LOGGER = logging.getLogger(__name__)
MAX_SAFE_THROTTLE = 100
WATCHDOG_INTERVAL_SECONDS = 3.0


@dataclass
class _ClientEntry:
    client: Any
    config: dict[str, str]
    tx_char: Any


@dataclass
class ToyController:
    state: ControllerState
    advisor: ThrusterAdvisor = field(default_factory=ThrusterAdvisor)
    max_throttle: int = MAX_SAFE_THROTTLE
    _pattern_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    _watchdog_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    _clients: dict[str, _ClientEntry] = field(default_factory=dict)
    _connection_logs: list[dict[str, Any]] = field(default_factory=list)

    async def connect(self, address: str) -> dict[str, str]:
        track = await self.state.get_track(address)
        if track is None:
            raise ValueError(f"Unknown toy address: {address}")
        local_name = track.details.get("local_name")
        track.profile = track.profile or resolve_device_profile(
            track.name,
            service_uuids=track.service_uuids,
            local_name=local_name if isinstance(local_name, str) else None,
        )
        if track.profile is None:
            raise ValueError(
                "Selected device is not a recognized Adorime/Galaku thruster. "
                "Look for an Adorime badge or Galaku service UUID in the scanner list."
            )
        if not track.present:
            raise ValueError("Toy is not currently in range.")

        if not track.levels:
            track.levels = {motor.id: 0 for motor in track.profile.motors}
        ble_device = await self.state.get_ble_device(address)
        await self.state.set_scanner_paused(True)
        try:
            await self._connect_live(address, track.profile, ble_device=ble_device)
        finally:
            await self.state.set_scanner_paused(False)
        await self.state.set_connection(address, True)
        self._start_watchdog(address)
        self._log_connection(address, track.name, "connected", "BLE connection established")
        return {"status": "connected", "address": address}

    async def disconnect(self, address: str) -> dict[str, str]:
        await self.stop_pattern(address)
        self._stop_watchdog(address)
        track = await self.state.get_track(address)
        if track and track.profile:
            zero_levels = {motor.id: 0 for motor in track.profile.motors}
            await self._send_levels(address, track.profile, zero_levels)
        await self._disconnect_live(address)
        await self.state.set_connection(address, False)
        self._log_connection(address, track.name if track else None, "disconnected", "BLE connection closed")
        return {"status": "disconnected", "address": address}

    async def set_levels(self, address: str, levels: dict[str, int]) -> dict[str, object]:
        track = await self.state.get_track(address)
        if track is None or track.profile is None:
            raise ValueError("Toy is not available for control.")
        if not track.connected:
            raise ValueError("Connect to the toy before sending control commands.")

        merged = {motor.id: track.levels.get(motor.id, 0) for motor in track.profile.motors}
        merged.update({key: int(value) for key, value in levels.items() if key in merged})
        merged = self._apply_safety_limits(merged)

        await self.stop_pattern(address)
        await self.state.set_levels(address, merged, pattern=None)
        await self._send_levels(address, track.profile, merged)
        self.advisor.record_manual_input(
            address=address,
            levels=merged,
            pattern=None,
            rssi=track.rssi,
        )
        return {"status": "ok", "address": address, "levels": merged}

    async def set_thruster(
        self,
        address: str,
        *,
        throttle: int,
        direction: str = "forward",
        pulse_mode: bool = False,
    ) -> dict[str, object]:
        track = await self.state.get_track(address)
        if track is None or track.profile is None:
            raise ValueError("Toy is not available for control.")
        if not track.connected:
            raise ValueError("Connect to the toy before sending control commands.")

        clamped = max(0, min(self.max_throttle, int(throttle)))
        if direction == "reverse":
            levels = {
                "thrust": max(0, self.max_throttle - clamped),
                "vibrate": clamped if track.profile.is_dual_motor else 0,
            }
        else:
            levels = {"thrust": clamped}
            if track.profile.is_dual_motor:
                levels["vibrate"] = track.levels.get("vibrate", 0)

        if pulse_mode:
            await self.run_pattern(address, "pulse")
            self.advisor.record_manual_input(
                address=address,
                levels=levels,
                pattern="pulse",
                rssi=track.rssi,
            )
            return {"status": "ok", "address": address, "pattern": "pulse", "levels": levels}

        return await self.set_levels(address, levels)

    async def apply_ai_suggestion(self, address: str) -> dict[str, object]:
        track = await self.state.get_track(address)
        if track is None or track.profile is None:
            raise ValueError("Toy is not available for control.")
        suggestion = self.advisor.suggest(
            address=address,
            current_levels=track.levels,
            rssi=track.rssi,
            connected=track.connected,
        )
        if track.connected:
            await self.set_levels(address, suggestion["suggested_levels"])
            if suggestion.get("suggested_pattern"):
                await self.run_pattern(address, suggestion["suggested_pattern"])
        return suggestion

    def connection_logs(self) -> list[dict[str, Any]]:
        return list(self._connection_logs)

    def _apply_safety_limits(self, levels: dict[str, int]) -> dict[str, int]:
        return {key: max(0, min(self.max_throttle, int(value))) for key, value in levels.items()}

    def _log_connection(
        self,
        address: str,
        name: str | None,
        event_type: str,
        message: str,
    ) -> None:
        self._connection_logs.append(
            {
                "type": event_type,
                "address": address,
                "name": name,
                "message": message,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )

    def _start_watchdog(self, address: str) -> None:
        self._stop_watchdog(address)
        self._watchdog_tasks[address] = asyncio.create_task(
            self._connection_watchdog(address),
            name=f"watchdog-{address}",
        )

    def _stop_watchdog(self, address: str) -> None:
        task = self._watchdog_tasks.pop(address, None)
        if task is not None:
            task.cancel()

    async def _connection_watchdog(self, address: str) -> None:
        try:
            while True:
                await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
                entry = self._clients.get(address)
                track = await self.state.get_track(address)
                if entry is None or track is None or not track.connected:
                    return
                if not entry.client.is_connected:
                    await self.state.add_system_event(
                        "connection-lost",
                        f"Lost connection to {address}; marking disconnected.",
                    )
                    self._log_connection(address, track.name, "disconnected", "Connection watchdog detected drop")
                    await self.state.set_connection(address, False)
                    await self._disconnect_live(address)
                    return
        except asyncio.CancelledError:
            raise

    async def run_pattern(self, address: str, pattern_id: str) -> dict[str, object]:
        track = await self.state.get_track(address)
        if track is None or track.profile is None:
            raise ValueError("Toy is not available for control.")
        if not track.connected:
            raise ValueError("Connect to the toy before running a pattern.")

        await self.stop_pattern(address)
        steps = pattern_steps(pattern_id)
        first_levels = levels_from_pattern(track.profile, steps[0])
        await self.state.set_levels(address, first_levels, pattern=pattern_id if pattern_id != "stop" else None)
        await self._send_levels(address, track.profile, first_levels)

        if pattern_id != "stop" and len(steps) > 1:
            self._pattern_tasks[address] = asyncio.create_task(
                self._pattern_loop(address, track.profile, pattern_id, steps),
                name=f"pattern-{address}",
            )
        return {"status": "ok", "address": address, "pattern": pattern_id}

    async def stop_pattern(self, address: str) -> None:
        task = self._pattern_tasks.pop(address, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _pattern_loop(
        self,
        address: str,
        profile: DeviceProfile,
        pattern_id: str,
        steps: list[dict[str, int]],
    ) -> None:
        index = 1
        try:
            while True:
                step = steps[index % len(steps)]
                levels = levels_from_pattern(profile, step)
                await self.state.set_levels(address, levels, pattern=pattern_id)
                await self._send_levels(address, profile, levels)
                await asyncio.sleep(0.9)
                index += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Pattern loop stopped for %s: %s", address, exc)
            await self.state.add_system_event("pattern-error", f"Pattern stopped for {address}: {exc}")

    async def _send_levels(self, address: str, profile: DeviceProfile, levels: dict[str, int]) -> None:
        payload = build_command(profile, levels)
        LOGGER.debug("Command for %s: %s -> %s", address, levels, payload.hex())
        try:
            await self._write_live(address, profile, payload)
        except Exception as exc:
            raise ValueError(f"Failed to send control command: {exc}") from exc

    async def _connect_live(
        self,
        address: str,
        profile: DeviceProfile,
        *,
        ble_device: Any = None,
    ) -> None:
        from bleak import BleakClient

        if address in self._clients:
            await self._disconnect_live(address)

        config = protocol_config(profile.protocol)
        target = ble_device if ble_device is not None else address
        client = BleakClient(target, timeout=20.0)
        try:
            await client.connect()
            if not client.is_connected:
                raise ValueError("device did not connect")

            service = client.services.get_service(config["service_uuid"])
            if service is None:
                raise ValueError(f"service {config['service_uuid']} not found")

            tx_char = service.get_characteristic(config["tx_uuid"])
            if tx_char is None:
                raise ValueError(f"characteristic {config['tx_uuid']} not found")

            self._clients[address] = _ClientEntry(client=client, config=config, tx_char=tx_char)
        except Exception as exc:
            with contextlib.suppress(Exception):
                if client.is_connected:
                    await client.disconnect()
            raise ValueError(f"Bluetooth connection failed: {exc}") from exc

    async def _disconnect_live(self, address: str) -> None:
        entry = self._clients.pop(address, None)
        if entry is None:
            return
        if entry.client.is_connected:
            await entry.client.disconnect()

    async def _write_live(self, address: str, profile: DeviceProfile, payload: bytes) -> None:
        entry = self._clients.get(address)
        if entry is None:
            ble_device = await self.state.get_ble_device(address)
            await self._connect_live(address, profile, ble_device=ble_device)
            entry = self._clients[address]

        client = entry.client
        if not client.is_connected:
            await client.connect()
            service = client.services.get_service(entry.config["service_uuid"])
            if service is None:
                raise ValueError(f"service {entry.config['service_uuid']} not found")
            tx_char = service.get_characteristic(entry.config["tx_uuid"])
            if tx_char is None:
                raise ValueError(f"characteristic {entry.config['tx_uuid']} not found")
            entry.tx_char = tx_char

        await client.write_gatt_char(entry.tx_char, payload, response=False)
