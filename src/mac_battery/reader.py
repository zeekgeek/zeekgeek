"""Battery sensor backends: macOS ioreg, Linux sysfs, SSH pull, and remote ingest."""

from __future__ import annotations

import json
import os
import platform
import plistlib
import random
import re
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metrics import BatterySample


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_signed_ma(value: int) -> int:
    """Normalize InstantAmperage which may arrive as unsigned wrap of int64/int32."""
    if value >= 2**63:
        value -= 2**64
    elif value >= 2**31:
        value -= 2**32
    return int(value)


def _plist_get(node: Any, key: str, default: Any = None) -> Any:
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for child in node.values():
            found = _plist_get(child, key, None)
            if found is not None:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _plist_get(child, key, None)
            if found is not None:
                return found
    return default


def _first_int(node: Any, *keys: str) -> int | None:
    for key in keys:
        value = _plist_get(node, key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_bool(node: Any, *keys: str) -> bool | None:
    for key in keys:
        value = _plist_get(node, key)
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"yes", "true", "1"}
    return None


def _first_str(node: Any, *keys: str) -> str:
    for key in keys:
        value = _plist_get(node, key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (bytes, bytearray)):
            try:
                return value.decode("utf-8", errors="ignore").strip()
            except Exception:
                continue
    return ""


def parse_ioreg_text(text: str) -> dict[str, Any]:
    """Best-effort parse of `ioreg` human text when -a plist is unavailable."""
    pattern = re.compile(r'"([^"]+)"\s*=\s*(Yes|No|-?\d+|".*?")')
    result: dict[str, Any] = {}
    for match in pattern.finditer(text):
        key, raw = match.group(1), match.group(2)
        if raw in {"Yes", "No"}:
            result[key] = raw == "Yes"
        elif raw.startswith('"'):
            result[key] = raw.strip('"')
        else:
            result[key] = int(raw)
    if not result:
        raise RuntimeError("Unable to parse AppleSmartBattery output")
    return result


def decode_ioreg_blob(data: bytes) -> Any:
    if not data.strip():
        raise RuntimeError("ioreg returned empty AppleSmartBattery data")
    try:
        return plistlib.loads(data)
    except Exception:
        return parse_ioreg_text(data.decode("utf-8", errors="replace"))


def sample_from_ioreg_tree(raw: Any, *, source: str = "ioreg") -> BatterySample:
    voltage = _first_int(raw, "Voltage")
    amperage = _first_int(raw, "InstantAmperage", "Amperage")
    if voltage is None or amperage is None:
        raise RuntimeError("AppleSmartBattery did not report Voltage/Amperage")

    design = _first_int(raw, "DesignCapacity") or 0
    max_cap = _first_int(raw, "AppleRawMaxCapacity", "MaxCapacity") or 0
    cur_cap = _first_int(raw, "AppleRawCurrentCapacity", "CurrentCapacity") or 0
    cycles = _first_int(raw, "CycleCount") or 0
    design_cycles = _first_int(raw, "DesignCycleCount9C") or 1000
    temp = _first_int(raw, "Temperature") or 0
    is_charging = _first_bool(raw, "IsCharging") or False
    external = _first_bool(raw, "ExternalConnected") or False
    fully = _first_bool(raw, "FullyCharged") or False
    time_rem = _first_int(raw, "TimeRemaining", "AvgTimeToFull")

    return BatterySample(
        timestamp=_now(),
        voltage_mv=voltage,
        amperage_ma=_as_signed_ma(amperage),
        design_capacity_mah=design,
        max_capacity_mah=max_cap,
        current_capacity_mah=cur_cap,
        cycle_count=cycles,
        design_cycle_count=design_cycles,
        temperature_cC=temp,
        is_charging=is_charging,
        external_connected=external,
        fully_charged=fully,
        apple_time_remaining_min=time_rem,
        serial=_first_str(raw, "BatterySerialNumber", "Serial"),
        device_name=_first_str(raw, "DeviceName"),
        manufacturer=_first_str(raw, "Manufacturer"),
        source=source,
    )


def sample_from_payload(payload: dict[str, Any], *, source: str | None = None) -> BatterySample:
    """Build a BatterySample from a collector / ingest JSON body."""
    required = ("voltage_mv", "amperage_ma", "design_capacity_mah", "max_capacity_mah", "current_capacity_mah")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"ingest payload missing keys: {', '.join(missing)}")

    status = str(payload.get("status", "")).lower()
    is_charging = bool(payload.get("is_charging", status == "charging"))
    external = bool(
        payload.get(
            "external_connected",
            is_charging or status in {"charging", "full", "not charging"},
        )
    )
    fully = bool(payload.get("fully_charged", status == "full"))

    if "temperature_cC" in payload and payload["temperature_cC"] is not None:
        temperature_cC = int(payload["temperature_cC"])
    elif payload.get("temperature_c") is not None:
        temperature_cC = int(float(payload["temperature_c"]) * 100)
    else:
        temperature_cC = 0

    return BatterySample(
        timestamp=_now(),
        voltage_mv=int(payload["voltage_mv"]),
        amperage_ma=_as_signed_ma(int(payload["amperage_ma"])),
        design_capacity_mah=int(payload["design_capacity_mah"]),
        max_capacity_mah=int(payload["max_capacity_mah"]),
        current_capacity_mah=int(payload["current_capacity_mah"]),
        cycle_count=int(payload.get("cycle_count", 0) or 0),
        design_cycle_count=int(payload.get("design_cycle_count", 1000) or 1000),
        temperature_cC=temperature_cC,
        is_charging=is_charging,
        external_connected=external,
        fully_charged=fully,
        apple_time_remaining_min=payload.get("apple_time_remaining_min"),
        serial=str(payload.get("serial", "") or ""),
        device_name=str(payload.get("device_name", "") or ""),
        manufacturer=str(payload.get("manufacturer", "") or ""),
        source=source or str(payload.get("source", "remote")),
    )


def sample_to_payload(sample: BatterySample) -> dict[str, Any]:
    return {
        "voltage_mv": sample.voltage_mv,
        "amperage_ma": sample.amperage_ma,
        "design_capacity_mah": sample.design_capacity_mah,
        "max_capacity_mah": sample.max_capacity_mah,
        "current_capacity_mah": sample.current_capacity_mah,
        "cycle_count": sample.cycle_count,
        "design_cycle_count": sample.design_cycle_count,
        "temperature_cC": sample.temperature_cC,
        "is_charging": sample.is_charging,
        "external_connected": sample.external_connected,
        "fully_charged": sample.fully_charged,
        "apple_time_remaining_min": sample.apple_time_remaining_min,
        "serial": sample.serial,
        "device_name": sample.device_name,
        "manufacturer": sample.manufacturer,
        "source": sample.source,
    }


class BatteryReader(ABC):
    @abstractmethod
    def read(self) -> BatterySample:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return type(self).__name__


class WaitingForSensor(RuntimeError):
    """Raised when a remote/SSH source has not produced a sample yet."""


class IORegBatteryReader(BatteryReader):
    """Live reader using local `ioreg -rn AppleSmartBattery -a` (macOS)."""

    def read(self) -> BatterySample:
        return sample_from_ioreg_tree(self._load_plist(), source="ioreg")

    def _load_plist(self) -> Any:
        try:
            completed = subprocess.run(
                ["ioreg", "-rn", "AppleSmartBattery", "-a"],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("ioreg not found — this reader requires macOS") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"ioreg failed: {exc.stderr.decode(errors='ignore')}") from exc
        return decode_ioreg_blob(completed.stdout)


class SshIORegBatteryReader(BatteryReader):
    """
    Pull AppleSmartBattery over SSH from a Mac.

    Example: SshIORegBatteryReader("user@macbook.local")
    Requires key-based SSH (BatchMode) to the Mac.
    """

    def __init__(self, target: str, *, ssh_binary: str = "ssh", extra_args: list[str] | None = None) -> None:
        if not target.strip():
            raise ValueError("SSH target is required, e.g. user@macbook.local")
        self.target = target.strip()
        self.ssh_binary = ssh_binary
        self.extra_args = list(extra_args or [])

    def read(self) -> BatterySample:
        cmd = [
            self.ssh_binary,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            *self.extra_args,
            self.target,
            "ioreg -rn AppleSmartBattery -a",
        ]
        try:
            completed = subprocess.run(cmd, check=True, capture_output=True, timeout=20)
        except FileNotFoundError as exc:
            raise RuntimeError("ssh binary not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"SSH timed out contacting {self.target}") from exc
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or b"").decode(errors="ignore").strip()
            raise RuntimeError(f"SSH ioreg failed ({self.target}): {err or exc}") from exc
        return sample_from_ioreg_tree(decode_ioreg_blob(completed.stdout), source=f"ssh:{self.target}")


class LinuxSysfsBatteryReader(BatteryReader):
    """
    Live reader for Linux power_supply class batteries.

    Reads `/sys/class/power_supply/BAT*` (or a custom root for tests).
    Units: voltage_now µV, current_now µA, charge_* µAh, temp decidegrees (0.1°C).
    """

    def __init__(self, root: str | Path = "/sys/class/power_supply") -> None:
        self.root = Path(root)
        self.path = self._find_battery(self.root)

    @staticmethod
    def _find_battery(root: Path) -> Path:
        if not root.exists():
            raise RuntimeError(f"power_supply path missing: {root}")
        candidates: list[Path] = []
        for entry in sorted(root.iterdir()):
            type_path = entry / "type"
            if type_path.is_file() and type_path.read_text(encoding="utf-8", errors="ignore").strip() == "Battery":
                candidates.append(entry)
            elif entry.name.upper().startswith("BAT"):
                candidates.append(entry)
        if not candidates:
            raise RuntimeError(f"No Battery device under {root}")
        return candidates[0]

    def _read_text(self, name: str) -> str | None:
        path = self.path / name
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="ignore").strip()

    def _read_int(self, name: str) -> int | None:
        raw = self._read_text(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def read(self) -> BatterySample:
        voltage_uv = self._read_int("voltage_now")
        current_ua = self._read_int("current_now")
        if voltage_uv is None:
            raise RuntimeError(f"{self.path} missing voltage_now")
        if current_ua is None:
            current_ua = 0

        # Prefer charge (µAh); fall back to energy (µWh) / voltage.
        design = self._read_int("charge_full_design")
        max_cap = self._read_int("charge_full")
        cur_cap = self._read_int("charge_now")
        if design is None or max_cap is None or cur_cap is None:
            energy_full_design = self._read_int("energy_full_design")
            energy_full = self._read_int("energy_full")
            energy_now = self._read_int("energy_now")
            if voltage_uv > 0 and energy_full_design is not None and energy_full is not None and energy_now is not None:
                # µWh / (µV) → Ah * 1000 → mAh roughly via (µWh * 1000) / µV
                design = int((energy_full_design * 1000) / voltage_uv)
                max_cap = int((energy_full * 1000) / voltage_uv)
                cur_cap = int((energy_now * 1000) / voltage_uv)
            else:
                design = design or 0
                max_cap = max_cap or 0
                cur_cap = cur_cap or 0

        # sysfs charge_* is µAh → mAh
        design_mah = int(design / 1000) if design else 0
        max_mah = int(max_cap / 1000) if max_cap else 0
        cur_mah = int(cur_cap / 1000) if cur_cap else 0

        status = (self._read_text("status") or "").lower()
        is_charging = status == "charging"
        fully = status == "full"
        external = is_charging or fully or status == "not charging"

        # current_now is usually absolute; sign from status
        amperage_ma = int(current_ua / 1000)
        if is_charging:
            amperage_ma = abs(amperage_ma)
        elif status == "discharging":
            amperage_ma = -abs(amperage_ma)

        temp_raw = self._read_int("temp")  # decidegrees C
        temp_cC = int(temp_raw * 10) if temp_raw is not None else 0

        cycles = self._read_int("cycle_count") or 0
        manufacturer = self._read_text("manufacturer") or ""
        model = self._read_text("model_name") or self._read_text("model") or ""
        serial = self._read_text("serial_number") or ""

        return BatterySample(
            timestamp=_now(),
            voltage_mv=int(voltage_uv / 1000),
            amperage_ma=amperage_ma,
            design_capacity_mah=design_mah,
            max_capacity_mah=max_mah,
            current_capacity_mah=cur_mah,
            cycle_count=cycles,
            design_cycle_count=1000,
            temperature_cC=temp_cC,
            is_charging=is_charging,
            external_connected=external,
            fully_charged=fully,
            apple_time_remaining_min=None,
            serial=serial,
            device_name=model,
            manufacturer=manufacturer,
            source=f"sysfs:{self.path.name}",
        )


class RemoteIngestBuffer(BatteryReader):
    """
    Holds the latest sample pushed by a remote Mac collector (HTTP ingest).

    The dashboard runs anywhere; the Mac posts live ioreg samples to /api/ingest.
    """

    def __init__(self, *, stale_after_s: float = 45.0) -> None:
        self.stale_after_s = stale_after_s
        self._lock = threading.Lock()
        self._sample: BatterySample | None = None
        self._updated_at = 0.0
        self._event = threading.Event()

    def push(self, sample: BatterySample) -> None:
        with self._lock:
            self._sample = sample
            self._updated_at = time.monotonic()
            self._event.set()

    def has_sample(self) -> bool:
        with self._lock:
            return self._sample is not None

    def age_s(self) -> float | None:
        with self._lock:
            if self._sample is None:
                return None
            return time.monotonic() - self._updated_at

    def read(self) -> BatterySample:
        with self._lock:
            sample = self._sample
            age = time.monotonic() - self._updated_at if sample is not None else None
        if sample is None:
            raise WaitingForSensor(
                "Waiting for remote Mac collector — run: "
                "python3 -m mac_battery.collect --url http://<this-host>:8780"
            )
        if age is not None and age > self.stale_after_s:
            raise WaitingForSensor(
                f"Remote sample is stale ({age:.0f}s old). Is the Mac collector still running?"
            )
        return sample

    def wait_for_sample(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout=timeout)


class DemoBatteryReader(BatteryReader):
    """Simulated 2018 MacBook Pro charge session."""

    def __init__(self, *, start_percent: float = 42.0, charge_ma: int = 3200) -> None:
        self.design_mah = 7336
        self.max_mah = 6250
        self.cycle_count = 487
        self.design_cycles = 1000
        self.serial = "D86DEMO2018MBP01"
        self.device_name = "bq20z451"
        self.manufacturer = "SMP"
        self._charge_ma = charge_ma
        self._capacity = int(self.max_mah * (start_percent / 100.0))
        self._last_tick = time.monotonic()
        self._plugged_in = True

    def read(self) -> BatterySample:
        now = time.monotonic()
        elapsed_h = (now - self._last_tick) / 3600.0
        self._last_tick = now

        charge_pct = 100.0 * self._capacity / self.max_mah
        if charge_pct >= 99.5:
            amperage = 0
            self._plugged_in = True
            fully = True
            is_charging = False
        elif self._plugged_in:
            fully = False
            is_charging = True
            if charge_pct < 80:
                amperage = self._charge_ma + random.randint(-120, 120)
            else:
                factor = max(0.08, (100.0 - charge_pct) / 20.0)
                amperage = int(self._charge_ma * factor) + random.randint(-40, 40)
            gained = int(amperage * elapsed_h)
            self._capacity = min(self.max_mah, self._capacity + max(0, gained))
        else:
            fully = False
            is_charging = False
            amperage = -random.randint(800, 1600)
            lost = int(abs(amperage) * elapsed_h)
            self._capacity = max(0, self._capacity - lost)

        charge_pct = 100.0 * self._capacity / self.max_mah
        voltage_mv = int(11000 + (charge_pct / 100.0) * 1700 + random.randint(-25, 25))
        temp = 3000 + random.randint(-40, 80) + (80 if is_charging else 0)
        remaining_mah = self.max_mah - self._capacity
        apple_eta = 65535
        if is_charging and amperage > 50:
            apple_eta = int((remaining_mah / amperage) * 60)

        return BatterySample(
            timestamp=_now(),
            voltage_mv=voltage_mv,
            amperage_ma=amperage,
            design_capacity_mah=self.design_mah,
            max_capacity_mah=self.max_mah,
            current_capacity_mah=self._capacity,
            cycle_count=self.cycle_count,
            design_cycle_count=self.design_cycles,
            temperature_cC=temp,
            is_charging=is_charging,
            external_connected=self._plugged_in,
            fully_charged=fully,
            apple_time_remaining_min=apple_eta,
            serial=self.serial,
            device_name=self.device_name,
            manufacturer=self.manufacturer,
            source="demo",
        )


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_linux() -> bool:
    return platform.system() == "Linux"


def probe_sysfs(root: str | Path = "/sys/class/power_supply") -> LinuxSysfsBatteryReader | None:
    try:
        reader = LinuxSysfsBatteryReader(root=root)
        reader.read()
        return reader
    except Exception:
        return None


def open_reader(
    *,
    source: str = "auto",
    force_demo: bool = False,
    auto_demo_fallback: bool = True,
    ssh_target: str | None = None,
    sysfs_root: str | Path = "/sys/class/power_supply",
    ingest: RemoteIngestBuffer | None = None,
) -> BatteryReader:
    """
    Select a battery backend.

    Sources:
      auto   — ioreg (macOS) → Linux sysfs → SSH (if --ssh) → demo fallback
      ioreg  — local AppleSmartBattery
      sysfs  — Linux /sys/class/power_supply
      ssh    — remote Mac via SSH + ioreg
      remote — wait for HTTP ingest from mac_battery.collect
      demo   — simulated session
    """
    chosen = "demo" if force_demo else source

    if chosen == "demo":
        return DemoBatteryReader()

    if chosen == "remote":
        return ingest or RemoteIngestBuffer()

    if chosen == "ioreg":
        reader = IORegBatteryReader()
        reader.read()
        return reader

    if chosen == "sysfs":
        reader = LinuxSysfsBatteryReader(root=sysfs_root)
        reader.read()
        return reader

    if chosen == "ssh":
        if not ssh_target:
            raise RuntimeError("--source ssh requires --ssh user@host")
        reader = SshIORegBatteryReader(ssh_target)
        reader.read()
        return reader

    if chosen != "auto":
        raise ValueError(f"Unknown battery source: {chosen}")

    # auto probe
    errors: list[str] = []

    if is_macos():
        try:
            reader = IORegBatteryReader()
            reader.read()
            return reader
        except Exception as exc:
            errors.append(f"ioreg: {exc}")

    if is_linux() or Path(sysfs_root).exists():
        probed = probe_sysfs(sysfs_root)
        if probed is not None:
            return probed
        errors.append(f"sysfs: no battery under {sysfs_root}")

    if ssh_target:
        try:
            reader = SshIORegBatteryReader(ssh_target)
            reader.read()
            return reader
        except Exception as exc:
            errors.append(f"ssh: {exc}")

    if auto_demo_fallback:
        return DemoBatteryReader()

    detail = "; ".join(errors) if errors else "no backends available"
    raise RuntimeError(
        "No live battery source available. "
        f"Tried auto-detect ({detail}). "
        "Use --source remote with a Mac collector, --ssh user@mac, or --demo."
    )


def sample_to_json(sample: BatterySample) -> str:
    return json.dumps(sample_to_payload(sample))
