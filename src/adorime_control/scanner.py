"""Bluetooth scanner backends for the AdoRime control app."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .ble_stack import compact_error_for_api, ensure_system_dbus_address
from .protocol import GALAKU_SERVICE_UUID, ADORIME_BLE_NAME_MAP
from .state import Observation, RadarState

LOGGER = logging.getLogger(__name__)


class ScannerBackend(Protocol):
    async def run(self) -> None:
        """Run the scanner until cancelled."""


@dataclass
class BleakScannerBackend:
    state: RadarState
    retry_seconds: float = 8.0

    async def run(self) -> None:
        ensure_system_dbus_address()
        try:
            from bleak import BleakScanner
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install the 'bleak' package for live Bluetooth scanning.") from exc

        attempt = 0
        while True:
            attempt += 1
            try:
                await self.state.set_scan_status(mode="live", error=None)
                scanner = BleakScanner(detection_callback=self._on_detection)
                LOGGER.info("Starting live Bluetooth scanner (AdoRime/Galaku discovery), attempt %s", attempt)
                async with scanner:
                    while True:
                        await asyncio.sleep(1)
                        await self.state.mark_stale()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                message = compact_error_for_api(exc)
                LOGGER.warning("Live scanner interrupted (%s); retrying in %.0fs", message, self.retry_seconds)
                await self.state.set_scan_status(mode="live-error", error=message)
                await self.state.add_system_event(
                    "scanner-retry",
                    f"Live scanner unavailable ({message}). Retrying in {self.retry_seconds:.0f}s…",
                )
                await asyncio.sleep(self.retry_seconds)

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
        await self.state.set_scan_status(mode="demo", error=None)
        LOGGER.info("Starting demo AdoRime scanner (simulated Galaku advertisements)")
        # Simulated advertisements use real AdoRime BLE local-name codes, not brand text.
        devices = [
            {
                "address": "A1:42:19:77:33:10",
                "name": "BGSF",
                "base": -62,
                "address_type": "random",
                "service_uuids": [GALAKU_SERVICE_UUID],
            },
            {
                "address": "D4:8A:FC:12:34:56",
                "name": "Keyboard",
                "base": -72,
                "address_type": "public",
                "service_uuids": [],
            },
            {
                "address": "7A:2B:91:AA:04:2F",
                "name": "QD48",
                "base": -76,
                "address_type": "random",
                "service_uuids": [GALAKU_SERVICE_UUID],
            },
            {
                "address": "DA:2B:91:AA:04:30",
                "name": "SN80",
                "base": -78,
                "address_type": "random",
                "service_uuids": [GALAKU_SERVICE_UUID],
            },
            # Unknown short code — exercises heuristic "probable" matching.
            {
                "address": "CE:11:22:33:44:55",
                "name": "ZX99",
                "base": -68,
                "address_type": "random",
                "service_uuids": [],
            },
            {
                "address": "11:22:33:44:55:66",
                "name": None,
                "base": -88,
                "address_type": "public",
                "service_uuids": [],
            },
        ]

        tick = 0
        while True:
            tick += 1
            for index, device in enumerate(devices):
                if index in {2, 3} and tick % 18 in {0, 1, 2, 3}:
                    continue
                if index == 2 and tick % 14 < 7:
                    continue
                if index == 3 and tick % 14 >= 7:
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
                        service_uuids=list(device["service_uuids"]),
                        observed_at=datetime.now(UTC),
                    )
                )
            await self.state.mark_stale()
            await asyncio.sleep(self.interval)


def _observation_from_bleak(device, advertisement_data) -> Observation:  # type: ignore[no-untyped-def]
    local_name = getattr(device, "name", None) or getattr(advertisement_data, "local_name", None)
    service_uuids = [str(uuid).lower() for uuid in (getattr(advertisement_data, "service_uuids", None) or [])]
    return Observation(
        address=getattr(device, "address", "unknown"),
        name=local_name,
        address_type=getattr(device, "address_type", None),
        tx_power=getattr(advertisement_data, "tx_power", None),
        service_uuids=service_uuids,
        rssi=int(getattr(advertisement_data, "rssi", getattr(device, "rssi", -127)) or -127),
        observed_at=datetime.now(UTC),
    )


def known_adorime_demo_names() -> dict[str, str]:
    return dict(ADORIME_BLE_NAME_MAP)
