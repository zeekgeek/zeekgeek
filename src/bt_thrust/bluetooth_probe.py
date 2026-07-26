"""Detect whether a live Bluetooth adapter is usable for BLE scanning."""

from __future__ import annotations

import asyncio
import logging
import shutil
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass
class AdapterProbeResult:
    available: bool
    adapter_name: str | None
    backend: str | None
    device_count: int
    error: str | None
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "adapter_name": self.adapter_name,
            "backend": self.backend,
            "device_count": self.device_count,
            "error": self.error,
            "details": self.details,
        }


async def probe_adapter(*, scan_seconds: float = 2.0) -> AdapterProbeResult:
    """Try a short Bleak scan to verify the OS Bluetooth stack is reachable."""
    details: dict[str, Any] = {
        "bluetoothctl": shutil.which("bluetoothctl"),
        "hcitool": shutil.which("hcitool"),
    }

    try:
        from bleak import BleakScanner

        scanner = BleakScanner()
        await scanner.start()
        await asyncio.sleep(max(0.5, scan_seconds))
        discovered = scanner.discovered_devices_and_advertisement_data
        backend = getattr(scanner, "backend_id", None)
        await scanner.stop()
        return AdapterProbeResult(
            available=True,
            adapter_name=str(backend) if backend else "default",
            backend=str(backend) if backend else None,
            device_count=len(discovered),
            error=None,
            details=details,
        )
    except ImportError as exc:
        return AdapterProbeResult(
            available=False,
            adapter_name=None,
            backend=None,
            device_count=0,
            error=f"bleak not installed: {exc}",
            details=details,
        )
    except Exception as exc:
        LOGGER.debug("Bluetooth adapter probe failed: %s", exc)
        with suppress(Exception):
            await scanner.stop()  # type: ignore[possibly-undefined]
        return AdapterProbeResult(
            available=False,
            adapter_name=None,
            backend=None,
            device_count=0,
            error=f"{type(exc).__name__}: {exc}",
            details=details,
        )
