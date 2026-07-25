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

        scanner = BleakScanner(scanning_mode="active")
        LOGGER.info("Starting live Bluetooth LE scan")
        await self.state.set_scanner_active(True, error=None)
        await self.state.add_system_event("scanner-live", "Live Bluetooth scanner active")

        await scanner.start()
        stale_task = asyncio.create_task(self._stale_loop(), name="scanner-stale")
        poll_task = asyncio.create_task(self._poll_loop(scanner), name="scanner-poll")

        try:
            async for device, adv_data in scanner.advertisement_data():
                await self._observe(device, adv_data)
        except asyncio.CancelledError:
            raise
        finally:
            stale_task.cancel()
            poll_task.cancel()
            await asyncio.gather(stale_task, poll_task, return_exceptions=True)
            with asyncio.suppress(Exception):
                await scanner.stop()

    async def _stale_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            await self.state.mark_stale()

    async def _poll_loop(self, scanner: Any) -> None:
        """Sync devices from the scanner cache (fallback if events are missed)."""
        while True:
            await asyncio.sleep(2)
            try:
                discovered = scanner.discovered_devices_and_advertisement_data
                for device, adv_data in discovered.values():
                    await self._observe(device, adv_data)
            except Exception as exc:
                LOGGER.debug("Scanner poll error: %s", exc)

    async def _observe(self, device: Any, advertisement_data: Any) -> None:
        observation = _observation_from_bleak(device, advertisement_data)
        observation.ble_device = device
        await self.state.observe(observation)


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


def _observation_from_bleak(device: Any, advertisement_data: Any) -> ToyObservation:
    manufacturer_data = getattr(advertisement_data, "manufacturer_data", None) or {}
    manufacturer_id = next(iter(manufacturer_data.keys()), None)
    service_uuids = list(getattr(advertisement_data, "service_uuids", None) or [])
    service_data = getattr(advertisement_data, "service_data", None) or {}
    local_name = getattr(advertisement_data, "local_name", None)
    device_name = getattr(device, "name", None)

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
        name=device_name or local_name,
        address_type=getattr(device, "address_type", None),
        manufacturer_id=manufacturer_id,
        service_uuids=service_uuids,
        tx_power=getattr(advertisement_data, "tx_power", None),
        rssi=int(getattr(advertisement_data, "rssi", getattr(device, "rssi", -127)) or -127),
        details=details,
        observed_at=datetime.now(UTC),
    )
