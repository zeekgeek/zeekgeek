"""Cross-platform BLE scanner built on Bleak.

Bleak uses CoreBluetooth on macOS and BlueZ on Linux.  macOS exposes an
OS-mediated scan and opaque peripheral UUIDs, not raw HCI packets or MAC
addresses.
"""

from __future__ import annotations

import asyncio
import contextlib
import platform
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from bleak import BleakScanner
from bleak.exc import (
    BleakBluetoothNotAvailableError,
    BleakBluetoothNotAvailableReason,
)

from parser import ManufacturerRecord, parse_manufacturer_data


UpdateCallback = Callable[["DiscoveredDevice"], None]
PRIVACY_NAME = re.compile(r"^(unknown|n/?a|null|none|device|ble[-_ ]?\w{0,4})$", re.I)
IS_MACOS = platform.system() == "Darwin"


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


def _rssi_from(device: Any, advertisement: Any) -> int:
    value = getattr(advertisement, "rssi", None)
    if value is None:
        value = getattr(device, "rssi", None)
    try:
        return int(value if value is not None else -127)
    except (TypeError, ValueError):
        return -127


def platform_scan_label() -> str:
    if IS_MACOS:
        return "LIVE BLE (macOS CoreBluetooth)"
    if platform.system() == "Linux":
        return "LIVE BLE (BlueZ)"
    return "LIVE BLE"


def macos_permission_hint() -> str:
    return (
        "On macOS: turn Bluetooth on, then grant Bluetooth permission to "
        "Terminal (or iTerm/Cursor) in System Settings → Privacy & Security → "
        "Bluetooth. Keep nearby devices advertising, and do not pass --demo."
    )


def bluetooth_error_message(error: Exception) -> str:
    """Turn Bleak availability failures into actionable operator guidance."""
    if isinstance(error, BleakBluetoothNotAvailableError):
        reason = error.reason
        actions = {
            BleakBluetoothNotAvailableReason.POWERED_OFF: (
                "Turn Bluetooth on in macOS Control Center, then retry."
            ),
            BleakBluetoothNotAvailableReason.DENIED_BY_USER: (
                "Allow the app that launched Python in System Settings → "
                "Privacy & Security → Bluetooth, then restart it."
            ),
            BleakBluetoothNotAvailableReason.DENIED_BY_SYSTEM: (
                "Bluetooth access is blocked by system policy. Ask the Mac "
                "administrator to allow it."
            ),
            BleakBluetoothNotAvailableReason.NO_BLUETOOTH: (
                "No Bluetooth radio is available to this process."
            ),
            BleakBluetoothNotAvailableReason.NO_BLE_CENTRAL_ROLE: (
                "The selected adapter cannot perform BLE central scanning."
            ),
        }
        action = actions.get(reason, macos_permission_hint())
        return f"{error.args[0]} {action}"
    return f"{type(error).__name__}: {error}"


async def probe_bluetooth(
    *, adapter: str | None = None, timeout: float = 1.0
) -> tuple[bool, str]:
    """Return whether a BLE adapter can start scanning on this host.

    On macOS this intentionally avoids a start/stop probe cycle. CoreBluetooth
    central managers are sensitive to rapid restart and permission prompts, so
    readiness is validated when the live scanner starts.
    """
    if IS_MACOS:
        return True, (
            "macOS CoreBluetooth ready — starting live advertisement scan. "
            + macos_permission_hint()
        )

    scanner_args: dict[str, Any] = {"scanning_mode": "active"}
    if adapter:
        scanner_args["adapter"] = adapter
    try:
        scanner = BleakScanner(**scanner_args)
        await scanner.start()
        try:
            await asyncio.sleep(max(timeout, 0.2))
        finally:
            await scanner.stop()
        return True, "Bluetooth adapter ready for live scanning"
    except FileNotFoundError as error:
        return (
            False,
            "No Bluetooth adapter / BlueZ socket found "
            f"({error}). Install BlueZ and enable bluetoothd, or use --demo.",
        )
    except Exception as error:  # bleak backend / permission failures
        return False, bluetooth_error_message(error)


class BluetoothRadarScanner:
    """Collect and merge BLE advertisements by platform-provided identifier."""

    def __init__(
        self,
        *,
        active: bool = True,
        adapter: str | None = None,
        on_update: UpdateCallback | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        if not active and IS_MACOS:
            raise ValueError(
                "CoreBluetooth does not support passive scanning on macOS; "
                "use --scan-mode active."
            )
        self.active = True if IS_MACOS else active
        self.adapter = adapter
        self.on_update = on_update
        self.loop = loop
        self.devices: dict[str, DiscoveredDevice] = {}
        self.packet_count = 0
        self.last_packet_at: float | None = None

    @staticmethod
    def _is_identity_limited(name: str | None) -> bool:
        normalized = (name or "").strip()
        return not normalized or bool(PRIVACY_NAME.fullmatch(normalized))

    def _build_device(
        self, device: Any, advertisement: Any
    ) -> DiscoveredDevice | None:
        address = str(getattr(device, "address", "") or "").strip()
        if not address:
            return None
        name = (
            getattr(advertisement, "local_name", None)
            or getattr(device, "name", None)
            or None
        )
        if isinstance(name, str):
            name = name.strip() or None
        manufacturer = parse_manufacturer_data(
            getattr(advertisement, "manufacturer_data", {}) or {}
        )
        now = time.time()
        current = self.devices.get(address)
        incoming_rssi = _rssi_from(device, advertisement)
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
        tx_power = getattr(advertisement, "tx_power", None)

        if current is None:
            current = DiscoveredDevice(
                address=address,
                name=name,
                rssi=incoming_rssi,
                tx_power=tx_power,
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
            if tx_power is not None:
                current.tx_power = tx_power
            current.service_uuids.update(incoming_services)
            current.service_data.update(incoming_service_data)
            if manufacturer:
                current.manufacturer_data = manufacturer
            current.last_seen = now
            current.sightings += 1
            current.identity_limited = self._is_identity_limited(current.name)

        self.packet_count += 1
        self.last_packet_at = now
        return current

    def _emit_update(self, record: DiscoveredDevice) -> None:
        if not self.on_update:
            return
        callback = self.on_update
        loop = self.loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                callback(record)
                return
        try:
            if loop.is_running():
                loop.call_soon_threadsafe(callback, record)
            else:
                callback(record)
        except RuntimeError:
            callback(record)

    def _detection_callback(self, device: Any, advertisement: Any) -> None:
        try:
            record = self._build_device(device, advertisement)
        except Exception:
            return
        if record is not None:
            self._emit_update(record)

    def _scanner_kwargs(self) -> dict[str, Any]:
        # CoreBluetooth only supports active scanning.
        scanner_args: dict[str, Any] = {
            "detection_callback": self._detection_callback,
            "scanning_mode": "active" if (self.active or IS_MACOS) else "passive",
        }
        if self.adapter and not IS_MACOS:
            scanner_args["adapter"] = self.adapter
        return scanner_args

    async def scan(self, duration: float) -> list[DiscoveredDevice]:
        if duration <= 0:
            raise ValueError("scan duration must be positive")
        if self.loop is None:
            self.loop = asyncio.get_running_loop()
        scanner = BleakScanner(**self._scanner_kwargs())
        await scanner.start()
        try:
            await asyncio.sleep(duration)
        finally:
            await scanner.stop()
        return list(self.devices.values())

    async def run_continuous(self) -> list[DiscoveredDevice]:
        """Keep one scanner session open until cancelled."""
        if self.loop is None:
            self.loop = asyncio.get_running_loop()
        scanner = BleakScanner(**self._scanner_kwargs())
        try:
            await scanner.start()
        except Exception as error:
            raise RuntimeError(
                "Failed to start live BLE scanner: "
                f"{bluetooth_error_message(error)}"
            ) from error
        try:
            while True:
                await asyncio.sleep(1.0)
        finally:
            with contextlib.suppress(Exception):
                await scanner.stop()
        return list(self.devices.values())


async def diagnose_live_scan(duration: float = 8.0) -> dict[str, Any]:
    """Run the same backend as the dashboard and report actual packet flow."""
    if duration <= 0:
        raise ValueError("diagnostic duration must be positive")

    observed: dict[str, DiscoveredDevice] = {}
    scanner = BluetoothRadarScanner(
        active=True,
        on_update=lambda device: observed.__setitem__(device.address, device),
    )
    started = time.time()
    error: str | None = None
    try:
        await scanner.scan(duration)
    except Exception as exc:
        error = bluetooth_error_message(exc)

    return {
        "platform": platform.platform(),
        "macos_version": platform.mac_ver()[0] if IS_MACOS else None,
        "backend": "CoreBluetooth" if IS_MACOS else (
            "BlueZ" if platform.system() == "Linux" else platform.system()
        ),
        "duration_seconds": round(time.time() - started, 2),
        "packets": scanner.packet_count,
        "devices": len(observed),
        "source": platform_scan_label(),
        "ok": error is None,
        "error": error,
        "permission_hint": macos_permission_hint() if IS_MACOS else None,
    }


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
