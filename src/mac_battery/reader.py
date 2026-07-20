"""Read AppleSmartBattery via ioreg, with a demo backend for non-Mac hosts."""

from __future__ import annotations

import json
import platform
import plistlib
import random
import re
import subprocess
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
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


class BatteryReader(ABC):
    @abstractmethod
    def read(self) -> BatterySample:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return type(self).__name__


class IORegBatteryReader(BatteryReader):
    """Live reader using `ioreg -rn AppleSmartBattery -a` (macOS)."""

    def read(self) -> BatterySample:
        raw = self._load_plist()
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
            source="ioreg",
        )

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

        data = completed.stdout
        if not data.strip():
            raise RuntimeError("ioreg returned empty AppleSmartBattery data")
        try:
            return plistlib.loads(data)
        except Exception:
            # Some older builds emit XML that plistlib handles; if not, try JSON-ish fallback.
            text = data.decode("utf-8", errors="replace")
            return self._parse_text_fallback(text)

    @staticmethod
    def _parse_text_fallback(text: str) -> dict[str, Any]:
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


class DemoBatteryReader(BatteryReader):
    """
    Simulated 2018 MacBook Pro charge session for hosts without Bluetooth/battery IOKit.

    Starts ~42% and charges toward 100% with realistic voltage/current curves.
    """

    def __init__(self, *, start_percent: float = 42.0, charge_ma: int = 3200) -> None:
        self.design_mah = 7336  # typical 15" 2018/2019 MBP class pack
        self.max_mah = 6250  # ~85% health worn pack
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
        # Taper current above 80% like real CC/CV charging.
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
                # Linear taper 80→100%
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
        # Pack voltage roughly 11.0–12.7 V across SoC for 3S packs.
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


def open_reader(*, force_demo: bool = False, auto_demo_fallback: bool = True) -> BatteryReader:
    if force_demo:
        return DemoBatteryReader()
    if not is_macos():
        if auto_demo_fallback:
            return DemoBatteryReader()
        raise RuntimeError("Live battery diagnostics require macOS (ioreg / AppleSmartBattery)")
    try:
        reader = IORegBatteryReader()
        reader.read()  # probe
        return reader
    except Exception:
        if auto_demo_fallback:
            return DemoBatteryReader()
        raise


def sample_to_json(sample: BatterySample) -> str:
    return json.dumps(
        {
            "voltage_mv": sample.voltage_mv,
            "amperage_ma": sample.amperage_ma,
            "watts": round(sample.watts, 2),
            "charge_percent": sample.charge_percent,
            "is_charging": sample.is_charging,
        }
    )
