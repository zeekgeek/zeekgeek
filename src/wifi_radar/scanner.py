"""WiFi scanning backends.

The live backend shells out to the Linux ``iw`` tool and parses the output of
``iw dev <iface> scan``. Each visible access point becomes a tracked target
keyed by BSSID, and its ``signal`` field feeds the RSSI history used for motion
classification. The demo backend simulates a mix of stationary and moving
devices (including one that walks toward the sensor) so the radar can be run
without WiFi hardware.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from .state import Observation, RadarState

LOGGER = logging.getLogger(__name__)


class ScannerBackend(Protocol):
    async def run(self) -> None:
        """Run the scanner until cancelled."""


@dataclass
class IwScannerBackend:
    """Live scanner backed by the Linux ``iw`` command."""

    state: RadarState
    interface: str | None = None
    interval: float = 3.0

    async def run(self) -> None:
        if shutil.which("iw") is None:
            raise RuntimeError("The 'iw' command is not installed; cannot run a live WiFi scan.")

        interface = self.interface or await self._detect_interface()
        if not interface:
            raise RuntimeError("No WiFi interface found (is a wireless adapter present?).")

        LOGGER.info("Starting live WiFi scan on interface %s", interface)
        while True:
            observations = await self._scan_once(interface)
            for observation in observations:
                await self.state.observe(observation)
            await self.state.mark_stale()
            await asyncio.sleep(self.interval)

    async def _detect_interface(self) -> str | None:
        stdout = await self._run_command(["iw", "dev"])
        match = re.search(r"Interface\s+(\S+)", stdout)
        return match.group(1) if match else None

    async def _scan_once(self, interface: str) -> list[Observation]:
        try:
            stdout = await self._run_command(["iw", "dev", interface, "scan"])
        except RuntimeError as exc:
            LOGGER.warning("WiFi scan failed: %s", exc)
            return []
        return parse_iw_scan(stdout)

    @staticmethod
    async def _run_command(command: list[str]) -> str:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace").strip() or f"{command[0]} exited {process.returncode}")
        return stdout.decode(errors="replace")


def parse_iw_scan(output: str) -> list[Observation]:
    """Parse ``iw dev <iface> scan`` output into observations."""
    observations: list[Observation] = []
    bssid: str | None = None
    ssid: str | None = None
    signal: int | None = None
    frequency: int | None = None
    channel: int | None = None
    now = datetime.now(UTC)

    def flush() -> None:
        nonlocal bssid, ssid, signal, frequency, channel
        if bssid is not None and signal is not None:
            observations.append(
                Observation(
                    bssid=bssid,
                    ssid=ssid or None,
                    rssi=signal,
                    channel=channel,
                    frequency_mhz=frequency,
                    observed_at=now,
                )
            )
        bssid = ssid = None
        signal = frequency = channel = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        bss_match = re.match(r"BSS\s+([0-9a-fA-F:]{17})", line)
        if bss_match:
            flush()
            bssid = bss_match.group(1).lower()
            continue
        if line.startswith("signal:"):
            signal_match = re.search(r"(-?\d+(?:\.\d+)?)\s*dBm", line)
            if signal_match:
                signal = int(round(float(signal_match.group(1))))
        elif line.startswith("freq:"):
            freq_match = re.search(r"freq:\s*(\d+)", line)
            if freq_match:
                frequency = int(freq_match.group(1))
                channel = _channel_from_freq(frequency)
        elif line.startswith("SSID:"):
            ssid = line[len("SSID:"):].strip()

    flush()
    return observations


def _channel_from_freq(freq_mhz: int) -> int | None:
    if 2412 <= freq_mhz <= 2472:
        return (freq_mhz - 2407) // 5
    if freq_mhz == 2484:
        return 14
    if 5000 <= freq_mhz <= 5900:
        return (freq_mhz - 5000) // 5
    return None


@dataclass
class _SimDevice:
    bssid: str
    ssid: str | None
    vendor: str
    channel: int
    frequency_mhz: int
    base_rssi: float
    behavior: str  # "stationary", "wander", or "approach"
    phase: float = field(default_factory=lambda: random.uniform(0, math.tau))


@dataclass
class DemoScannerBackend:
    """Simulated scanner with a mix of stationary and moving devices."""

    state: RadarState
    interval: float = 1.0

    def __post_init__(self) -> None:
        self._devices = [
            _SimDevice("a0:11:22:33:44:01", "HomeRouter", "Netgear", 6, 2437, -68, "stationary"),
            _SimDevice("a0:11:22:33:44:02", "OfficeAP", "Cisco", 36, 5180, -75, "stationary"),
            _SimDevice("b4:aa:bb:cc:dd:03", "SmartTV", "Samsung", 11, 2462, -72, "wander"),
            _SimDevice("c8:de:ad:be:ef:04", None, "Espressif", 1, 2412, -86, "approach"),
        ]

    async def run(self) -> None:
        LOGGER.info("Starting demo WiFi scan simulator")
        tick = 0
        while True:
            tick += 1
            for device in self._devices:
                rssi = self._rssi_for(device, tick)
                await self.state.observe(
                    Observation(
                        bssid=device.bssid,
                        ssid=device.ssid,
                        rssi=rssi,
                        channel=device.channel,
                        frequency_mhz=device.frequency_mhz,
                        vendor=device.vendor,
                        observed_at=datetime.now(UTC),
                    )
                )
            await self.state.mark_stale()
            await asyncio.sleep(self.interval)

    @staticmethod
    def _rssi_for(device: _SimDevice, tick: int) -> int:
        if device.behavior == "stationary":
            # Small measurement noise only; signal stays flat.
            return int(round(device.base_rssi + random.uniform(-1.2, 1.2)))
        if device.behavior == "wander":
            # Slow drift back and forth plus noise.
            drift = 10 * math.sin(tick / 9 + device.phase)
            return int(round(device.base_rssi + drift + random.uniform(-2, 2)))
        # "approach": walk toward the sensor over ~25 ticks, then reset far away.
        cycle = tick % 40
        gain = min(cycle, 25) * 1.4  # up to +35 dBm stronger as it nears
        return int(round(device.base_rssi + gain + random.uniform(-1.5, 1.5)))
