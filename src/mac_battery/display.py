"""Terminal rendering for live battery diagnostics."""

from __future__ import annotations

import os
import shutil
from typing import Any

from .metrics import format_duration


def _clear() -> None:
    # Prefer ANSI home/clear so scrollback is not wiped aggressively on every tick
    print("\033[H\033[J", end="")


def _bar(percent: float | None, width: int = 28) -> str:
    if percent is None:
        return "[" + ("?" * width) + "]"
    pct = max(0.0, min(100.0, percent))
    filled = int(round((pct / 100.0) * width))
    return "[" + ("█" * filled) + ("░" * (width - filled)) + f"] {pct:5.1f}%"


def _polarity(amperage_ma: int) -> str:
    if amperage_ma > 50:
        return "charging into battery"
    if amperage_ma < -50:
        return "discharging (powering Mac)"
    return "idle / trickle"


def render_snapshot(report: dict[str, Any], *, header: str | None = None) -> str:
    e = report["electrical"]
    c = report["charging"]
    h = report["health"]
    cols = shutil.get_terminal_size((88, 24)).columns
    rule = "─" * min(cols, 72)

    lines = [
        header or "MacBook Battery Diagnostic",
        rule,
        f"  Source: {report.get('source', '?')}    Updated: {report.get('timestamp', '')}",
        "",
        "  LIVE ELECTRICALS",
        f"    Voltage     {e['voltage_v']:7.3f} V     ({e['voltage_mv']} mV)",
        f"    Amperage    {e['amperage_a']:7.3f} A     ({e['amperage_ma']} mA)  {_polarity(e['amperage_ma'])}",
        f"    Power       {e['watts']:7.2f} W",
        f"    Temp        {e['temperature_c']:7.2f} °C",
        "",
        "  CHARGE STATUS",
        f"    Adapter     {'connected' if c['adapter_connected'] else 'unplugged'}",
        f"    Charging    {'yes' if c['is_charging'] else 'no'}",
        f"    Fully charged {'yes' if c['fully_charged'] else 'no'}",
        f"    Level       {_bar(c['charge_percent'])}",
        "",
        "  TIME TO TARGET",
        f"    → 80%       {c['eta_to_80_label']}",
        f"    → Full      {c['eta_to_full_label']}",
    ]
    if c.get("apple_time_remaining_min") is not None:
        lines.append(f"    Apple ETA   {format_duration(float(c['apple_time_remaining_min']))}")
    if e.get("smoothed_amperage_ma") is not None:
        lines.append(f"    Rate (avg)  {e['smoothed_amperage_ma']:.0f} mA smoothed")

    lines += [
        "",
        "  BATTERY HEALTH",
        f"    Health      {_bar(h['health_percent'])}  {h['health_band']}",
        f"    Design      {h['design_capacity_mah']} mAh",
        f"    Max now     {h['max_capacity_mah']} mAh",
        f"    Current     {h['current_capacity_mah']} mAh",
        f"    Cycles      {h['cycle_count']} / {h['design_cycle_count']}"
        f"  ({'—' if h['cycle_life_used_percent'] is None else str(h['cycle_life_used_percent']) + '%'} used)"
        f"  {h['cycle_band']}",
    ]
    if h.get("manufacturer") or h.get("device_name") or h.get("serial"):
        lines.append(
            f"    Pack        {h.get('manufacturer', '')} {h.get('device_name', '')}  "
            f"S/N {h.get('serial', '')}".rstrip()
        )
    lines += ["", rule, "  Ctrl+C to quit  ·  targets: 80% optimized charge / 100% full"]
    return "\n".join(lines)


def print_live(report: dict[str, Any], *, clear: bool = True) -> None:
    if clear and os.isatty(1):
        _clear()
    print(render_snapshot(report))
