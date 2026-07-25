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

# Simulated nearby devices — all RSSI bases are >= -85 dBm (strong/nearby).
DEMO_DEVICES: list[dict[str, object]] = [
    {
        "address": "D4:8A:FC:12:34:01",
        "name": "BGSF",
        "manufacturer_id": 0x004C,
        "base": -54,
        "service_uuids": [GALAKU_SERVICE_UUID, "0000180f-0000-1000-8000-00805f9b34fb"],
    },
    {
        "address": "E2:11:AA:22:33:02",
        "name": "SN80",
        "manufacturer_id": 0x004C,
        "base": -58,
        "service_uuids": [GALAKU_SERVICE_UUID],
    },
    {
        "address": "7A:2B:91:AA:04:2F",
        "name": "iPhone",
        "manufacturer_id": 0x004C,
        "base": -62,
        "service_uuids": [],
    },
    {
        "address": "A1:B2:C3:D4:E5:04",
        "name": "MacBook Pro",
        "manufacturer_id": 0x004C,
        "base": -65,
        "service_uuids": ["0000180a-0000-1000-8000-00805f9b34fb"],
    },
    {
        "address": "B3:C4:D5:E6:F7:05",
        "name": "AirPods Pro",
        "manufacturer_id": 0x004C,
        "base": -68,
        "service_uuids": ["0000180f-0000-1000-8000-00805f9b34fb"],
    },
    {
        "address": "C1:44:09:33:71:B8",
        "name": "BLE Speaker",
        "manufacturer_id": 0x0499,
        "base": -70,
        "service_uuids": ["0000180a-0000-1000-8000-00805f9b34fb"],
    },
    {
        "address": "D5:E6:F7:A8:B9:06",
        "name": "Galaxy Watch",
        "manufacturer_id": 0x0075,
        "base": -72,
        "service_uuids": ["00001800-0000-1000-8000-00805f9b34fb"],
    },
    {
        "address": "E6:F7:A8:B9:CA:07",
        "name": "MX Keys",
        "manufacturer_id": 0x046D,
        "base": -74,
        "service_uuids": ["00001812-0000-1000-8000-00805f9b34fb"],
    },
    {
        "address": "F7:A8:B9:CA:DB:08",
        "name": "Fit Band 6",
        "manufacturer_id": 0x0157,
        "base": -78,
        "service_uuids": [],
    },
    {
        "address": "A8:B9:CA:DB:EC:09",
        "name": "Smart Bulb",
        "manufacturer_id": 0x0215,
        "base": -82,
        "service_uuids": ["00001829-0000-1000-8000-00805f9b34fb"],
    },
]


@dataclass
class DemoScannerBackend:
    state: ControllerState
    interval: float = 1.5

    async def run(self) -> None:
        LOGGER.info("Starting demo Bluetooth scan simulator")
        await self.state.set_scanner_active(True, error=None)
        await self.state.add_system_event(
            "scanner-demo",
            "Demo scanner active — simulating 10 nearby devices (≥ -85 dBm).",
        )

        tick = 0
        while True:
            tick += 1
            for index, device in enumerate(DEMO_DEVICES):
                if index == 2 and tick % 19 in {0, 1}:
                    continue
                drift = int(8 * random.uniform(-1, 1))
                manufacturer_id = int(device["manufacturer_id"])  # type: ignore[arg-type]
                await self.state.observe(
                    ToyObservation(
                        address=str(device["address"]),
                        name=str(device["name"]),
                        manufacturer_id=manufacturer_id,
                        address_type="random" if index % 3 else "public",
                        rssi=int(device["base"]) + drift,  # type: ignore[arg-type]
                        service_uuids=list(device["service_uuids"]),  # type: ignore[arg-type]
                        tx_power=-12,
                        details={
                            "local_name": device["name"],
                            "is_connectable": True,
                            "manufacturer_data": [
                                {
                                    "company_hex": f"0x{manufacturer_id:04x}",
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
