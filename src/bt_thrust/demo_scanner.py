"""Demo Bluetooth scanner for environments without a live adapter."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime

from .protocols import GALAKU_SERVICE_UUID
from .state import ControllerState, ToyObservation

LOGGER = logging.getLogger(__name__)


@dataclass
class DemoScannerBackend:
    state: ControllerState
    interval: float = 1.5

    async def run(self) -> None:
        LOGGER.info("Starting demo Bluetooth scan simulator")
        await self.state.set_scanner_active(True, error=None)
        await self.state.add_system_event(
            "scanner-demo",
            "Demo scanner active (no Bluetooth adapter). Use live hardware without --demo.",
        )

        devices = [
            {
                "address": "D4:8A:FC:12:34:01",
                "name": "BGSF",
                "manufacturer_id": 0x004C,
                "base": -54,
                "service_uuids": [GALAKU_SERVICE_UUID, "0000180f-0000-1000-8000-00805f9b34fb"],
            },
            {
                "address": "7A:2B:91:AA:04:2F",
                "name": "iPhone",
                "manufacturer_id": 0x004C,
                "base": -68,
                "service_uuids": [],
            },
            {
                "address": "C1:44:09:33:71:B8",
                "name": "BLE Speaker",
                "manufacturer_id": 0x0499,
                "base": -72,
                "service_uuids": ["0000180a-0000-1000-8000-00805f9b34fb"],
            },
        ]

        tick = 0
        while True:
            tick += 1
            for index, device in enumerate(devices):
                if index == 1 and tick % 19 in {0, 1}:
                    continue
                drift = int(10 * random.uniform(-1, 1))
                await self.state.observe(
                    ToyObservation(
                        address=device["address"],
                        name=device["name"],
                        manufacturer_id=device["manufacturer_id"],
                        address_type="random" if index else "public",
                        rssi=int(device["base"]) + drift,
                        service_uuids=list(device["service_uuids"]),
                        tx_power=-12,
                        details={
                            "local_name": device["name"],
                            "is_connectable": True,
                            "manufacturer_data": [
                                {
                                    "company_hex": f"0x{device['manufacturer_id']:04x}",
                                    "data_hex": "010203",
                                    "data_length": 3,
                                }
                            ],
                        },
                        observed_at=datetime.now(UTC),
                    )
                )
            await self.state.mark_stale()
            await asyncio.sleep(self.interval)
