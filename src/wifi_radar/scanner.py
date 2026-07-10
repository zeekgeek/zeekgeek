"""WiFi scanning backends with optional monitor-mode client capture."""

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

from .monitor import MonitorModeController, run_command
from .state import ClientObservation, Observation, RadarState

LOGGER = logging.getLogger(__name__)

MAC_RE = re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")
DBM_RE = re.compile(r"(-?\d+)\s*dBm")
BEACON_RE = re.compile(r"Beacon(?:\s*\((.*?)\))?")
PROBE_REQ_RE = re.compile(r"Probe Request(?:\s*\((.*?)\))?")
PROBE_RESP_RE = re.compile(r"Probe Response(?:\s*\((.*?)\))?")


class ScannerBackend(Protocol):
    async def run(self) -> None:
        """Run the scanner until cancelled."""


@dataclass
class IwScannerBackend:
    """Live scanner backed by `iw` plus optional monitor frame capture."""

    state: RadarState
    interface: str | None = None
    interval: float = 3.0
    monitor_mode: bool = False
    monitor_interface: str | None = None
    monitor_capture_seconds: float = 2.0

    async def run(self) -> None:
        if shutil.which("iw") is None:
            raise RuntimeError("The 'iw' command is not installed; cannot run a live WiFi scan.")

        controller = MonitorModeController(run_command)
        base_interface = await controller.detect_base_interface(self.interface)
        if not base_interface:
            raise RuntimeError("No WiFi interface found (is a wireless adapter present?).")

        activation = None
        if self.monitor_mode:
            activation = await controller.enable(base_interface, preferred_monitor_interface=self.monitor_interface)
            await self.state.set_monitor_status(
                enabled=True,
                base_interface=activation.base_interface,
                monitor_interface=activation.monitor_interface,
                note=activation.note,
            )
        else:
            await self.state.set_monitor_status(
                enabled=False,
                base_interface=base_interface,
                monitor_interface=None,
                note=f"Monitor mode disabled on {base_interface}.",
            )

        LOGGER.info(
            "Starting live WiFi scan on %s%s",
            base_interface,
            f" with monitor {activation.monitor_interface}" if activation else "",
        )

        try:
            while True:
                ap_observations: list[Observation] = []
                client_observations: list[ClientObservation] = []

                if activation is None or activation.monitor_interface != base_interface:
                    ap_observations.extend(await self._scan_once(base_interface))

                if activation is not None:
                    monitor_output = await self._capture_monitor_frames(activation.monitor_interface)
                    monitor_aps, monitor_clients = parse_monitor_capture(
                        monitor_output,
                        known_ap_bssids={item.bssid for item in ap_observations},
                    )
                    ap_observations.extend(monitor_aps)
                    client_observations.extend(monitor_clients)

                for observation in _dedupe_ap_observations(ap_observations):
                    await self.state.observe(observation)
                for client in _dedupe_client_observations(client_observations):
                    await self.state.observe_client(client)

                await self.state.mark_stale()
                await asyncio.sleep(self.interval)
        finally:
            if activation is not None:
                await controller.restore(activation)
                await self.state.set_monitor_status(
                    enabled=False,
                    base_interface=activation.base_interface,
                    monitor_interface=None,
                    note=f"Restored {activation.base_interface} to managed mode.",
                )

    async def _scan_once(self, interface: str) -> list[Observation]:
        try:
            stdout = await run_command(["iw", "dev", interface, "scan"])
        except RuntimeError as exc:
            LOGGER.warning("WiFi AP scan failed: %s", exc)
            return []
        return parse_iw_scan(stdout)

    async def _capture_monitor_frames(self, interface: str) -> str:
        if shutil.which("tcpdump") is None:
            raise RuntimeError("The 'tcpdump' command is required for monitor-mode client capture.")
        process = await asyncio.create_subprocess_exec(
            "tcpdump",
            "-I",
            "-i",
            interface,
            "-nn",
            "-e",
            "-s",
            "256",
            "-c",
            "140",
            "type",
            "mgt",
            "or",
            "type",
            "data",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=max(self.monitor_capture_seconds, 1.0))
        except TimeoutError:
            process.terminate()
            stdout, stderr = await process.communicate()
        if process.returncode not in {0, 124, -15, -2} and not stdout:
            raise RuntimeError(stderr.decode(errors="replace").strip() or "tcpdump capture failed.")
        return stdout.decode(errors="replace")


def parse_iw_scan(output: str) -> list[Observation]:
    """Parse `iw dev <iface> scan` output into AP observations."""
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
            ssid = line[len("SSID:") :].strip()

    flush()
    return observations


def parse_monitor_capture(output: str, known_ap_bssids: set[str] | None = None) -> tuple[list[Observation], list[ClientObservation]]:
    """Parse tcpdump monitor output into AP and client observations."""
    now = datetime.now(UTC)
    known_aps = {item.lower() for item in (known_ap_bssids or set())}
    ap_observations: list[Observation] = []
    client_observations: list[ClientObservation] = []

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        macs = [item.lower() for item in MAC_RE.findall(line)]
        if not macs:
            continue
        signal = _extract_signal(line)

        beacon_match = BEACON_RE.search(line) or PROBE_RESP_RE.search(line)
        if beacon_match:
            bssid = macs[0]
            known_aps.add(bssid)
            ssid = (beacon_match.group(1) or "").strip() or None
            ap_observations.append(
                Observation(
                    bssid=bssid,
                    ssid=ssid,
                    rssi=signal if signal is not None else -82,
                    observed_at=now,
                )
            )
            continue

        probe_match = PROBE_REQ_RE.search(line)
        if probe_match:
            client_observations.append(
                ClientObservation(
                    mac=macs[0],
                    associated_bssid=None,
                    rssi=signal,
                    frame_type="probe-request",
                    probe_ssid=(probe_match.group(1) or "").strip() or None,
                    observed_at=now,
                )
            )
            continue

        ap_mac = next((item for item in macs if item in known_aps), None)
        client_candidates = [item for item in macs if not _is_broadcast_or_multicast(item) and item != ap_mac]
        if client_candidates:
            client_observations.append(
                ClientObservation(
                    mac=client_candidates[0],
                    associated_bssid=ap_mac,
                    rssi=signal,
                    frame_type="data",
                    observed_at=now,
                )
            )
    return ap_observations, client_observations


def _extract_signal(line: str) -> int | None:
    match = DBM_RE.search(line)
    if not match:
        return None
    return int(match.group(1))


def _channel_from_freq(freq_mhz: int) -> int | None:
    if 2412 <= freq_mhz <= 2472:
        return (freq_mhz - 2407) // 5
    if freq_mhz == 2484:
        return 14
    if 5000 <= freq_mhz <= 5900:
        return (freq_mhz - 5000) // 5
    return None


def _is_broadcast_or_multicast(mac: str) -> bool:
    if mac == "ff:ff:ff:ff:ff:ff":
        return True
    first_octet = int(mac.split(":")[0], 16)
    return bool(first_octet & 0x01)


def _dedupe_ap_observations(observations: list[Observation]) -> list[Observation]:
    grouped: dict[str, Observation] = {}
    for item in observations:
        existing = grouped.get(item.bssid)
        if existing is None or item.rssi > existing.rssi:
            grouped[item.bssid] = item
    return list(grouped.values())


def _dedupe_client_observations(observations: list[ClientObservation]) -> list[ClientObservation]:
    grouped: dict[str, ClientObservation] = {}
    for item in observations:
        existing = grouped.get(item.mac)
        if existing is None:
            grouped[item.mac] = item
            continue
        if item.associated_bssid and not existing.associated_bssid:
            grouped[item.mac] = item
        elif (item.rssi or -999) > (existing.rssi or -999):
            grouped[item.mac] = item
    return list(grouped.values())


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
class _SimClient:
    mac: str
    attached_to: str | None
    behavior: str  # "steady", "roam", "probe"
    base_rssi: float
    phase: float = field(default_factory=lambda: random.uniform(0, math.tau))


@dataclass
class DemoScannerBackend:
    """Simulated scanner with AP and client traffic."""

    state: RadarState
    interval: float = 1.0

    def __post_init__(self) -> None:
        self._devices = [
            _SimDevice("a0:11:22:33:44:01", "HomeRouter", "Netgear", 6, 2437, -68, "stationary"),
            _SimDevice("a0:11:22:33:44:02", "OfficeAP", "Cisco", 36, 5180, -75, "stationary"),
            _SimDevice("b4:aa:bb:cc:dd:03", "SmartTV", "Samsung", 11, 2462, -72, "wander"),
            _SimDevice("c8:de:ad:be:ef:04", None, "Espressif", 1, 2412, -86, "approach"),
        ]
        self._clients = [
            _SimClient("02:10:20:30:40:50", "a0:11:22:33:44:01", "steady", -66),
            _SimClient("36:aa:bb:cc:dd:ee", "a0:11:22:33:44:02", "roam", -72),
            _SimClient("7a:01:02:03:04:05", None, "probe", -80),
        ]

    async def run(self) -> None:
        LOGGER.info("Starting demo WiFi scan simulator")
        tick = 0
        while True:
            tick += 1
            now = datetime.now(UTC)
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
                        observed_at=now,
                    )
                )

            for client in self._clients:
                rssi = self._client_rssi_for(client, tick)
                associated = client.attached_to
                frame_type = "data"
                probe_ssid = None
                if client.behavior == "roam" and tick % 20 in {0, 1, 2}:
                    associated = random.choice([item.bssid for item in self._devices[:2]])
                if client.behavior == "probe" and tick % 4 == 0:
                    frame_type = "probe-request"
                    probe_ssid = random.choice(["GuestWiFi", "IoT", "Cafe-WLAN", ""])
                await self.state.observe_client(
                    ClientObservation(
                        mac=client.mac,
                        associated_bssid=associated,
                        rssi=rssi,
                        frame_type=frame_type,
                        probe_ssid=probe_ssid or None,
                        observed_at=now,
                    )
                )

            await self.state.mark_stale()
            await asyncio.sleep(self.interval)

    @staticmethod
    def _rssi_for(device: _SimDevice, tick: int) -> int:
        if device.behavior == "stationary":
            return int(round(device.base_rssi + random.uniform(-1.2, 1.2)))
        if device.behavior == "wander":
            drift = 10 * math.sin(tick / 9 + device.phase)
            return int(round(device.base_rssi + drift + random.uniform(-2, 2)))
        cycle = tick % 40
        gain = min(cycle, 25) * 1.4
        return int(round(device.base_rssi + gain + random.uniform(-1.5, 1.5)))

    @staticmethod
    def _client_rssi_for(client: _SimClient, tick: int) -> int:
        if client.behavior == "steady":
            return int(round(client.base_rssi + random.uniform(-2.0, 2.0)))
        if client.behavior == "roam":
            drift = 6 * math.sin(tick / 5 + client.phase)
            return int(round(client.base_rssi + drift + random.uniform(-3, 3)))
        return int(round(client.base_rssi + random.uniform(-4, 4)))
