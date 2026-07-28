"""Cross-platform BLE scanner built on Bleak.

Bleak uses CoreBluetooth on macOS and BlueZ on Linux.  macOS exposes an
OS-mediated scan and opaque peripheral UUIDs, not raw HCI packets or MAC
addresses.
"""

from __future__ import annotations

import asyncio
import platform
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from bleak import BleakScanner

from parser import ManufacturerRecord, parse_manufacturer_data


UpdateCallback = Callable[["DiscoveredDevice"], None]
PRIVACY_NAME = re.compile(r"^(unknown|n/?a|null|none|device|ble[-_ ]?\w{0,4})$", re.I)


@dataclass
class DiscoveredDevice:
    address: str
    name: str | None
    rssi: int
    tx_power: int | None
    service_uuids: set[str] = field(default_factory=set)
    service_data: dict[str, str] = field(default_factory=dict)
    manufacturer_data: list[ManufacturerRecord] = field(default_factory=list)
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    sightings: int = 1
    identity_limited: bool = False

    @property
    def display_name(self) -> str:
        return self.name or "🕵️ Hidden"

    @property
    def ecosystems(self) -> set[str]:
        return {
            item.ecosystem for item in self.manufacturer_data if item.ecosystem
        }

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["service_uuids"] = sorted(self.service_uuids)
        result["manufacturer_data"] = [
            record.as_dict() for record in self.manufacturer_data
        ]
        result["ecosystems"] = sorted(self.ecosystems)
        return result


class BluetoothRadarScanner:
    """Collect and merge BLE advertisements by platform-provided identifier."""

    def __init__(
        self,
        *,
        active: bool = False,
        adapter: str | None = None,
        on_update: UpdateCallback | None = None,
    ) -> None:
        if not active and platform.system() == "Darwin":
            raise ValueError(
                "CoreBluetooth does not expose passive-scan selection on macOS; "
                "choose active mode or run passive mode with BlueZ on Linux."
            )
        self.active = active
        self.adapter = adapter
        self.on_update = on_update
        self.devices: dict[str, DiscoveredDevice] = {}

    @staticmethod
    def _is_identity_limited(name: str | None) -> bool:
        normalized = (name or "").strip()
        return not normalized or bool(PRIVACY_NAME.fullmatch(normalized))

    def _detection_callback(self, device: Any, advertisement: Any) -> None:
        address = str(getattr(device, "address", "") or getattr(device, "name", ""))
        if not address:
            return
        name = (
            getattr(advertisement, "local_name", None)
            or getattr(device, "name", None)
            or None
        )
        manufacturer = parse_manufacturer_data(
            getattr(advertisement, "manufacturer_data", {}) or {}
        )
        now = time.time()
        current = self.devices.get(address)
        incoming_rssi = int(getattr(advertisement, "rssi", -127))
        incoming_services = {
            str(uuid).lower()
            for uuid in (getattr(advertisement, "service_uuids", []) or [])
        }
        incoming_service_data = {
            str(uuid).lower(): bytes(payload).hex()
            for uuid, payload in (
                getattr(advertisement, "service_data", {}) or {}
            ).items()
        }

        if current is None:
            current = DiscoveredDevice(
                address=address,
                name=name,
                rssi=incoming_rssi,
                tx_power=getattr(advertisement, "tx_power", None),
                service_uuids=incoming_services,
                service_data=incoming_service_data,
                manufacturer_data=manufacturer,
                first_seen=now,
                last_seen=now,
                identity_limited=self._is_identity_limited(name),
            )
            self.devices[address] = current
        else:
            current.name = name or current.name
            current.rssi = incoming_rssi
            current.tx_power = (
                getattr(advertisement, "tx_power", None)
                if getattr(advertisement, "tx_power", None) is not None
                else current.tx_power
            )
            current.service_uuids.update(incoming_services)
            current.service_data.update(incoming_service_data)
            if manufacturer:
                current.manufacturer_data = manufacturer
            current.last_seen = now
            current.sightings += 1
            current.identity_limited = self._is_identity_limited(current.name)

        if self.on_update:
            self.on_update(current)

    async def scan(self, duration: float) -> list[DiscoveredDevice]:
        if duration <= 0:
            raise ValueError("scan duration must be positive")
        scanner_args: dict[str, Any] = {
            "detection_callback": self._detection_callback,
            "scanning_mode": "active" if self.active else "passive",
        }
        if self.adapter:
            scanner_args["adapter"] = self.adapter
        scanner = BleakScanner(**scanner_args)
        await scanner.start()
        try:
            await asyncio.sleep(duration)
        finally:
            await scanner.stop()
        return list(self.devices.values())


async def demo_scan(
    duration: float, on_update: UpdateCallback | None = None
) -> list[DiscoveredDevice]:
    """Deterministic hardware-free scan used for evaluation and training."""
    records = [
        DiscoveredDevice(
            "D1:00:00:00:00:01",
            "Living Room Hub",
            -44,
            -8,
            {"0000fe2c-0000-1000-8000-00805f9b34fb"},
            manufacturer_data=parse_manufacturer_data({0x00E0: b"\x01\x10"}),
        ),
        DiscoveredDevice(
            "D1:00:00:00:00:02",
            None,
            -57,
            None,
            {"0000fe2c-0000-1000-8000-00805f9b34fb"},
            manufacturer_data=parse_manufacturer_data({0x00E0: b"\x02\x01"}),
            identity_limited=True,
        ),
        DiscoveredDevice(
            "D1:00:00:00:00:03",
            "Watch",
            -63,
            -12,
            {"0000180f-0000-1000-8000-00805f9b34fb"},
            manufacturer_data=parse_manufacturer_data({0x004C: b"\x10\x02"}),
        ),
        DiscoveredDevice(
            "D1:00:00:00:00:04",
            None,
            -82,
            None,
            set(),
            manufacturer_data=parse_manufacturer_data({0x0157: b"\x01"}),
            identity_limited=True,
        ),
    ]
    delay = min(max(duration / len(records), 0.05), 0.5)
    for record in records:
        if on_update:
            on_update(record)
        await asyncio.sleep(delay)
    return records

