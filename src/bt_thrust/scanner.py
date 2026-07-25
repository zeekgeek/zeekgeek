"""Bluetooth toy scanning backends."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .state import ControllerState, ToyObservation

LOGGER = logging.getLogger(__name__)

GALAKU_SERVICE = "00001000-0000-1000-8000-00805f9b34fb"


class ScannerBackend(Protocol):
    async def run(self) -> None:
        """Run the scanner until cancelled."""


@dataclass
class BleakScannerBackend:
    state: ControllerState

    async def run(self) -> None:
        try:
            from bleak import BleakScanner
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install the 'bleak' package to use live Bluetooth scanning.") from exc

        scanner = BleakScanner(detection_callback=self._on_detection)
        LOGGER.info("Starting Bluetooth LE toy scan")
        async with scanner:
            while True:
                await asyncio.sleep(1)
                await self.state.mark_stale()

    def _on_detection(self, device, advertisement_data) -> None:  # type: ignore[no-untyped-def]
        observation = _observation_from_bleak(device, advertisement_data)
        if not _looks_like_toy(observation):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.state.observe(observation))


@dataclass
class DemoScannerBackend:
    state: ControllerState
    interval: float = 1.0

    async def run(self) -> None:
        LOGGER.info("Starting demo toy scan simulator")
        devices = [
            {
                "address": "E5:7E:98:C4:F7:01",
                "name": "BGSF",
                "base": -54,
                "service_uuids": [GALAKU_SERVICE],
            },
            {
                "address": "E5:7E:98:C4:F7:02",
                "name": "SN80",
                "base": -61,
                "service_uuids": [GALAKU_SERVICE],
            },
            {
                "address": "E5:7E:98:C4:F7:03",
                "name": "AX05",
                "base": -68,
                "service_uuids": [GALAKU_SERVICE],
            },
            {
                "address": "E5:7E:98:C4:F7:04",
                "name": "G312",
                "base": -72,
                "service_uuids": [GALAKU_SERVICE],
            },
            {
                "address": "E5:7E:98:C4:F7:05",
                "name": "QD48",
                "base": -77,
                "service_uuids": [GALAKU_SERVICE],
            },
            {
                "address": "AA:BB:CC:DD:EE:FF",
                "name": "Unknown-BLE",
                "base": -82,
                "service_uuids": [],
            },
        ]

        tick = 0
        while True:
            tick += 1
            for index, device in enumerate(devices):
                if index == 5 and tick % 19 in {0, 1}:
                    continue
                drift = int(8 * random.uniform(-1, 1))
                if index == 0:
                    drift += 10 if tick % 20 < 8 else -6
                await self.state.observe(
                    ToyObservation(
                        address=device["address"],
                        name=device["name"],
                        rssi=int(device["base"]) + drift,
                        service_uuids=device["service_uuids"],
                        observed_at=datetime.now(UTC),
                    )
                )
            await self.state.mark_stale()
            await asyncio.sleep(self.interval)


def _observation_from_bleak(device, advertisement_data) -> ToyObservation:  # type: ignore[no-untyped-def]
    manufacturer_id = None
    manufacturer_data = getattr(advertisement_data, "manufacturer_data", None) or {}
    if manufacturer_data:
        manufacturer_id = next(iter(manufacturer_data.keys()))

    return ToyObservation(
        address=getattr(device, "address", "unknown"),
        name=getattr(device, "name", None) or getattr(advertisement_data, "local_name", None),
        manufacturer_id=manufacturer_id,
        service_uuids=list(getattr(advertisement_data, "service_uuids", None) or []),
        rssi=int(getattr(advertisement_data, "rssi", getattr(device, "rssi", -127)) or -127),
        observed_at=datetime.now(UTC),
    )


def _looks_like_toy(observation: ToyObservation) -> bool:
    from .protocols import match_device_profile

    if match_device_profile(observation.name):
        return True
    if GALAKU_SERVICE in observation.service_uuids:
        return True
    if observation.name and len(observation.name.strip()) <= 8 and observation.name.isupper():
        return True
    return False
