"""Live Adorime Bluetooth scanning."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from .protocols import match_adorime_profile
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
        LOGGER.info("Starting live Adorime BLE scan")
        await self.state.add_system_event("scanner-live", "Live Adorime scanner active")
        async with scanner:
            while True:
                await asyncio.sleep(1)
                await self.state.mark_stale()

    def _on_detection(self, device, advertisement_data) -> None:  # type: ignore[no-untyped-def]
        observation = _observation_from_bleak(device, advertisement_data)
        if match_adorime_profile(observation.name) is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.state.observe(observation))


def _observation_from_bleak(device, advertisement_data) -> ToyObservation:  # type: ignore[no-untyped-def]
    manufacturer_id = None
    manufacturer_data = getattr(advertisement_data, "manufacturer_data", None) or {}
    if manufacturer_data:
        manufacturer_id = next(iter(manufacturer_data.keys()))

    details = {
        "platform_data": repr(getattr(device, "details", None)),
        "local_name": getattr(advertisement_data, "local_name", None),
    }
    return ToyObservation(
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
