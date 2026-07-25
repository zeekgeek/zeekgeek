"""Live toy connection and GATT command backend."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from .protocols import (
    DeviceProfile,
    build_command,
    levels_from_pattern,
    pattern_steps,
    protocol_config,
)
from .state import ControllerState

LOGGER = logging.getLogger(__name__)


@dataclass
class _ClientEntry:
    client: Any
    config: dict[str, str]
    tx_char: Any


@dataclass
class ToyController:
    state: ControllerState
    _pattern_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    _clients: dict[str, _ClientEntry] = field(default_factory=dict)

    async def connect(self, address: str) -> dict[str, str]:
        track = await self.state.get_track(address)
        if track is None:
            raise ValueError(f"Unknown toy address: {address}")
        if track.profile is None:
            raise ValueError("Selected device is not a recognized controllable toy profile.")
        if not track.present:
            raise ValueError("Toy is not currently in range.")

        await self._connect_live(address, track.profile)
        await self.state.set_connection(address, True)
        return {"status": "connected", "address": address}

    async def disconnect(self, address: str) -> dict[str, str]:
        await self.stop_pattern(address)
        track = await self.state.get_track(address)
        if track and track.profile:
            zero_levels = {motor.id: 0 for motor in track.profile.motors}
            await self._send_levels(address, track.profile, zero_levels)
        await self._disconnect_live(address)
        await self.state.set_connection(address, False)
        return {"status": "disconnected", "address": address}

    async def set_levels(self, address: str, levels: dict[str, int]) -> dict[str, object]:
        track = await self.state.get_track(address)
        if track is None or track.profile is None:
            raise ValueError("Toy is not available for control.")
        if not track.connected:
            raise ValueError("Connect to the toy before sending control commands.")

        merged = {motor.id: track.levels.get(motor.id, 0) for motor in track.profile.motors}
        merged.update({key: int(value) for key, value in levels.items() if key in merged})

        await self.stop_pattern(address)
        await self.state.set_levels(address, merged, pattern=None)
        await self._send_levels(address, track.profile, merged)
        return {"status": "ok", "address": address, "levels": merged}

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

    async def _connect_live(self, address: str, profile: DeviceProfile) -> None:
        from bleak import BleakClient

        if address in self._clients:
            await self._disconnect_live(address)

        config = protocol_config(profile.protocol)
        client = BleakClient(address, timeout=20.0)
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
            await self._connect_live(address, profile)
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
