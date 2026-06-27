"""Bluetooth scanning backends."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .state import Observation, RadarState

LOGGER = logging.getLogger(__name__)


class ScannerBackend(Protocol):
    async def run(self) -> None:
        """Run the scanner until cancelled."""


@dataclass
class BleakScannerBackend:
    state: RadarState

    async def run(self) -> None:
        try:
            from bleak import BleakScanner
        except ImportError as exc:  # pragma: no cover - exercised only without optional dependency
            raise RuntimeError("Install the 'bleak' package to use live Bluetooth scanning.") from exc

        scanner = BleakScanner(detection_callback=self._on_detection)
        LOGGER.info("Starting Bluetooth LE scan")
        async with scanner:
            while True:
                await asyncio.sleep(1)
                await self.state.mark_stale()

    def _on_detection(self, device, advertisement_data) -> None:  # type: ignore[no-untyped-def]
        observation = _observation_from_bleak(device, advertisement_data)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.state.observe(observation))


@dataclass
class DemoScannerBackend:
    state: RadarState
    interval: float = 1.0

    async def run(self) -> None:
        LOGGER.info("Starting demo Bluetooth scan simulator")
        devices = [
            {
                "address": "D4:8A:FC:12:34:56",
                "name": "Keyboard",
                "manufacturer_id": 76,
                "base": -58,
                "address_type": "public",
            },
            {
                "address": "7A:2B:91:AA:04:2F",
                "name": None,
                "manufacturer_id": None,
                "base": -77,
                "address_type": "random",
            },
            {
                "address": "C1:44:09:33:71:B8",
                "name": "BLE Beacon 12",
                "manufacturer_id": 1177,
                "base": -68,
                "address_type": "random",
            },
        ]

        tick = 0
        while True:
            tick += 1
            for index, device in enumerate(devices):
                if index == 1 and tick % 17 in {0, 1, 2, 3}:
                    continue
                drift = int(12 * random.uniform(-1, 1))
                if index == 2:
                    drift += 18 if tick % 24 < 10 else -18
                await self.state.observe(
                    Observation(
                        address=device["address"],
                        name=device["name"],
                        manufacturer_id=device["manufacturer_id"],
                        address_type=device["address_type"],
                        rssi=int(device["base"]) + drift,
                        service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"] if index == 0 else [],
                        observed_at=datetime.now(UTC),
                    )
                )
            await self.state.mark_stale()
            await asyncio.sleep(self.interval)


def _observation_from_bleak(device, advertisement_data) -> Observation:  # type: ignore[no-untyped-def]
    manufacturer_id = None
    manufacturer_data = getattr(advertisement_data, "manufacturer_data", None) or {}
    if manufacturer_data:
        manufacturer_id = next(iter(manufacturer_data.keys()))

    details = {
        "platform_data": repr(getattr(device, "details", None)),
        "local_name": getattr(advertisement_data, "local_name", None),
    }
    return Observation(
        address=getattr(device, "address", "unknown"),
        name=getattr(device, "name", None) or getattr(advertisement_data, "local_name", None),
        address_type=getattr(device, "address_type", None),
        manufacturer_id=manufacturer_id,
        service_uuids=list(getattr(advertisement_data, "service_uuids", None) or []),
        tx_power=getattr(advertisement_data, "tx_power", None),
        rssi=int(getattr(advertisement_data, "rssi", getattr(device, "rssi", -127)) or -127),
        details=details,
        observed_at=datetime.now(UTC),
    )
