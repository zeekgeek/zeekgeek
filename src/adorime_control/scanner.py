"""Bluetooth scanner backends for the AdoRime control app."""

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
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install the 'bleak' package for live Bluetooth scanning.") from exc

        scanner = BleakScanner(detection_callback=self._on_detection)
        LOGGER.info("Starting live Bluetooth scanner")
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
        LOGGER.info("Starting demo AdoRime scanner")
        devices = [
            {
                "address": "A1:42:19:77:33:10",
                "name": "AdoRime Thrust Pod",
                "base": -62,
                "address_type": "random",
            },
            {
                "address": "D4:8A:FC:12:34:56",
                "name": "Keyboard",
                "base": -72,
                "address_type": "public",
            },
            {
                "address": "7A:2B:91:AA:04:2F",
                "name": "AdoRime Vector",
                "base": -76,
                "address_type": "random",
            },
        ]

        tick = 0
        while True:
            tick += 1
            for index, device in enumerate(devices):
                if index == 2 and tick % 18 in {0, 1, 2}:
                    continue
                drift = int(10 * random.uniform(-1, 1))
                if index == 0:
                    drift += 15 if tick % 20 < 8 else -10
                await self.state.observe(
                    Observation(
                        address=device["address"],
                        name=device["name"],
                        address_type=device["address_type"],
                        rssi=int(device["base"]) + drift,
                        observed_at=datetime.now(UTC),
                    )
                )
            await self.state.mark_stale()
            await asyncio.sleep(self.interval)


def _observation_from_bleak(device, advertisement_data) -> Observation:  # type: ignore[no-untyped-def]
    return Observation(
        address=getattr(device, "address", "unknown"),
        name=getattr(device, "name", None) or getattr(advertisement_data, "local_name", None),
        address_type=getattr(device, "address_type", None),
        tx_power=getattr(advertisement_data, "tx_power", None),
        rssi=int(getattr(advertisement_data, "rssi", getattr(device, "rssi", -127)) or -127),
        observed_at=datetime.now(UTC),
    )
