"""Classic Bluetooth discovery via bluetoothctl (Linux)."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

LOGGER = logging.getLogger(__name__)

DEVICE_LINE = re.compile(
    r"^Device\s+(?P<address>[0-9A-Fa-f:]{17})\s+(?P<name>.+)$"
)


@dataclass
class ClassicDevice:
    address: str
    name: str
    device_class: str | None = None
    rssi: int | None = None
    observed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "name": self.name,
            "device_class": self.device_class,
            "rssi": self.rssi,
            "transport": "classic",
            "observed_at": self.observed_at.isoformat(timespec="seconds") if self.observed_at else None,
        }


def classic_scan_available() -> bool:
    return shutil.which("bluetoothctl") is not None


async def scan_classic_devices(*, duration_seconds: float = 8.0) -> list[ClassicDevice]:
    if not classic_scan_available():
        return []

    script = "\n".join(
        [
            "power on",
            "agent on",
            "default-agent",
            "scan on",
            f"sleep {max(3, int(duration_seconds))}",
            "scan off",
            "devices",
            "quit",
        ]
    )
    try:
        process = await asyncio.create_subprocess_exec(
            "bluetoothctl",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(script.encode("utf-8")),
            timeout=duration_seconds + 10.0,
        )
    except (asyncio.TimeoutError, FileNotFoundError, OSError) as exc:
        LOGGER.warning("Classic Bluetooth scan failed: %s", exc)
        return []

    if process.returncode not in (0, None):
        LOGGER.debug("bluetoothctl stderr: %s", stderr_bytes.decode("utf-8", errors="replace"))

    now = datetime.now(UTC)
    devices: dict[str, ClassicDevice] = {}
    for line in stdout_bytes.decode("utf-8", errors="replace").splitlines():
        match = DEVICE_LINE.match(line.strip())
        if match is None:
            continue
        address = match.group("address").upper()
        devices[address] = ClassicDevice(
            address=address,
            name=match.group("name").strip(),
            observed_at=now,
        )
    return list(devices.values())
