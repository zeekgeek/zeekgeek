"""Battery sample model and derived health / ETA metrics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque


@dataclass(frozen=True)
class BatterySample:
    """One instantaneous reading from AppleSmartBattery (or demo)."""

    timestamp: datetime
    voltage_mv: int
    amperage_ma: int  # signed: + charging into pack, − discharging
    design_capacity_mah: int
    max_capacity_mah: int
    current_capacity_mah: int
    cycle_count: int
    design_cycle_count: int
    temperature_cC: int  # hundredths of °C
    is_charging: bool
    external_connected: bool
    fully_charged: bool
    apple_time_remaining_min: int | None  # 65535 / None = unknown
    serial: str = ""
    device_name: str = ""
    manufacturer: str = ""
    source: str = "live"

    @property
    def voltage_v(self) -> float:
        return self.voltage_mv / 1000.0

    @property
    def amperage_a(self) -> float:
        return self.amperage_ma / 1000.0

    @property
    def watts(self) -> float:
        return self.voltage_v * self.amperage_a

    @property
    def temperature_c(self) -> float:
        return self.temperature_cC / 100.0

    @property
    def health_percent(self) -> float | None:
        if self.design_capacity_mah <= 0:
            return None
        # Some macOS builds report MaxCapacity as 0–100 (% of design).
        if self.max_capacity_mah <= 100:
            return float(self.max_capacity_mah)
        return 100.0 * self.max_capacity_mah / self.design_capacity_mah

    @property
    def charge_percent(self) -> float | None:
        if self.max_capacity_mah <= 0:
            return None
        if self.max_capacity_mah <= 100:
            # CurrentCapacity is also a percentage in that mode.
            return float(self.current_capacity_mah)
        return 100.0 * self.current_capacity_mah / self.max_capacity_mah

    @property
    def cycle_life_used_percent(self) -> float | None:
        limit = self.design_cycle_count or 1000
        if limit <= 0:
            return None
        return 100.0 * self.cycle_count / limit

    def capacity_at_percent(self, percent: float) -> int | None:
        """Target absolute capacity (mAh) for a charge level of `percent` of max."""
        if self.max_capacity_mah <= 0:
            return None
        if self.max_capacity_mah <= 100:
            # Percent mode: treat current/max as percentages already.
            return int(round(percent))
        return int(round(self.max_capacity_mah * (percent / 100.0)))


@dataclass
class ChargeRateTracker:
    """Smooth recent charge current for stable ETA estimates."""

    window: int = 12
    _samples: Deque[int] = field(default_factory=deque)

    def add(self, amperage_ma: int) -> None:
        self._samples.append(amperage_ma)
        while len(self._samples) > self.window:
            self._samples.popleft()

    @property
    def average_ma(self) -> float | None:
        if not self._samples:
            return None
        return sum(self._samples) / len(self._samples)

    def eta_minutes_to_capacity(self, sample: BatterySample, target_mah: int) -> float | None:
        """Minutes until current capacity reaches target_mah at smoothed charge rate."""
        if sample.max_capacity_mah <= 100:
            # Percent mode: current_capacity_mah is already %.
            remaining = target_mah - sample.current_capacity_mah
            # Approximate mAh remaining using design capacity scale when raw mAh unavailable.
            scale = sample.design_capacity_mah if sample.design_capacity_mah > 0 else 7000
            remaining_mah = remaining / 100.0 * scale
        else:
            remaining_mah = target_mah - sample.current_capacity_mah

        if remaining_mah <= 0:
            return 0.0

        rate = self.average_ma
        if rate is None:
            rate = float(sample.amperage_ma)
        if rate is None or rate <= 50:  # ignore tiny / zero / discharge rates
            return None
        # hours = mAh / mA → minutes
        return (remaining_mah / rate) * 60.0


def format_duration(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    if minutes <= 0:
        return "reached"
    total = int(round(minutes))
    hours, mins = divmod(total, 60)
    if hours <= 0:
        return f"{mins} min"
    return f"{hours} h {mins:02d} min"


def health_band(health: float | None) -> str:
    if health is None:
        return "unknown"
    if health >= 90:
        return "Excellent"
    if health >= 80:
        return "Good"
    if health >= 70:
        return "Fair"
    return "Poor — consider replacement"


def cycle_band(cycles: int, limit: int) -> str:
    limit = limit or 1000
    if cycles < 300:
        return "Low wear"
    if cycles < 700:
        return "Moderate wear"
    if cycles < limit:
        return "High wear — near rated life"
    return "At/over rated cycle life"


def build_report(
    sample: BatterySample,
    rate: ChargeRateTracker,
    *,
    target_optimized: float = 80.0,
) -> dict:
    """Structured snapshot used by CLI and web dashboard."""
    charge_pct = sample.charge_percent
    health = sample.health_percent
    target_mah = sample.capacity_at_percent(target_optimized)
    full_mah = sample.capacity_at_percent(100.0)

    eta_80 = rate.eta_minutes_to_capacity(sample, target_mah) if target_mah is not None else None
    eta_full = rate.eta_minutes_to_capacity(sample, full_mah) if full_mah is not None else None

    already_80 = charge_pct is not None and charge_pct >= target_optimized
    already_full = sample.fully_charged or (charge_pct is not None and charge_pct >= 99.5)

    apple_eta = sample.apple_time_remaining_min
    if apple_eta is not None and apple_eta >= 65535:
        apple_eta = None

    avg_ma = rate.average_ma
    return {
        "timestamp": sample.timestamp.astimezone(timezone.utc).isoformat(),
        "source": sample.source,
        "electrical": {
            "voltage_v": round(sample.voltage_v, 3),
            "voltage_mv": sample.voltage_mv,
            "amperage_a": round(sample.amperage_a, 3),
            "amperage_ma": sample.amperage_ma,
            "smoothed_amperage_ma": None if avg_ma is None else round(avg_ma, 1),
            "watts": round(sample.watts, 2),
            "temperature_c": round(sample.temperature_c, 2),
        },
        "charging": {
            "adapter_connected": sample.external_connected,
            "is_charging": sample.is_charging,
            "fully_charged": sample.fully_charged,
            "charge_percent": None if charge_pct is None else round(charge_pct, 1),
            "apple_time_remaining_min": apple_eta,
            "eta_to_80_min": None if already_80 else (None if eta_80 is None else round(eta_80, 1)),
            "eta_to_full_min": None if already_full else (None if eta_full is None else round(eta_full, 1)),
            "eta_to_80_label": "already ≥ 80%" if already_80 else format_duration(eta_80),
            "eta_to_full_label": "full" if already_full else format_duration(eta_full),
            "optimized_target_percent": target_optimized,
        },
        "health": {
            "design_capacity_mah": sample.design_capacity_mah,
            "max_capacity_mah": sample.max_capacity_mah,
            "current_capacity_mah": sample.current_capacity_mah,
            "health_percent": None if health is None else round(health, 1),
            "health_band": health_band(health),
            "cycle_count": sample.cycle_count,
            "design_cycle_count": sample.design_cycle_count or 1000,
            "cycle_life_used_percent": (
                None
                if sample.cycle_life_used_percent is None
                else round(sample.cycle_life_used_percent, 1)
            ),
            "cycle_band": cycle_band(sample.cycle_count, sample.design_cycle_count or 1000),
            "serial": sample.serial,
            "device_name": sample.device_name,
            "manufacturer": sample.manufacturer,
        },
    }
