"""Live Bluetooth scanning for nearby devices."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .state import ControllerState, ToyObservation

LOGGER = logging.getLogger(__name__)


@dataclass
class BleakScannerBackend:
    state: ControllerState

    async def run(self) -> None:
        try:
            from bleak import BleakScanner
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install the 'bleak' package to use live Bluetooth scanning.") from exc

        scanner = BleakScanner(detection_callback=self._on_detection)
        LOGGER.info("Starting live Bluetooth LE scan")
        await self.state.set_scanner_active(True)
        await self.state.add_system_event("scanner-live", "Live Bluetooth scanner active")
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


def _format_manufacturer_data(manufacturer_data: dict[int, bytes]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for company_id, payload in manufacturer_data.items():
        entries.append(
            {
                "company_id": company_id,
                "company_hex": f"0x{company_id:04x}",
                "data_hex": payload.hex(),
                "data_length": len(payload),
            }
        )
    return entries


def _observation_from_bleak(device, advertisement_data) -> ToyObservation:  # type: ignore[no-untyped-def]
    manufacturer_data = getattr(advertisement_data, "manufacturer_data", None) or {}
    manufacturer_id = next(iter(manufacturer_data.keys()), None)
    service_uuids = list(getattr(advertisement_data, "service_uuids", None) or [])
    service_data = getattr(advertisement_data, "service_data", None) or {}
    local_name = getattr(advertisement_data, "local_name", None)

    details: dict[str, Any] = {
        "platform_data": repr(getattr(device, "details", None)),
        "local_name": local_name,
        "manufacturer_data": _format_manufacturer_data(manufacturer_data),
        "service_data": {
            str(uuid): payload.hex() for uuid, payload in service_data.items()
        },
        "is_connectable": getattr(advertisement_data, "is_connectable", None),
    }
    return ToyObservation(
        address=getattr(device, "address", "unknown"),
        name=getattr(device, "name", None) or local_name,
        address_type=getattr(device, "address_type", None),
        manufacturer_id=manufacturer_id,
        service_uuids=service_uuids,
        tx_power=getattr(advertisement_data, "tx_power", None),
        rssi=int(getattr(advertisement_data, "rssi", getattr(device, "rssi", -127)) or -127),
        details=details,
        observed_at=datetime.now(UTC),
    )
