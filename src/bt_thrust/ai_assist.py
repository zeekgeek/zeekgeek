"""Heuristic AI-assisted thruster control suggestions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .signal_quality import signal_quality_label


@dataclass
class ThrusterAdvisor:
    history_limit: int = 40
    _manual_inputs: deque[dict[str, Any]] = field(default_factory=deque)
    _auto_tune_enabled: bool = False

    def record_manual_input(
        self,
        *,
        address: str,
        levels: dict[str, int],
        pattern: str | None = None,
        rssi: int | None = None,
    ) -> None:
        self._manual_inputs.append(
            {
                "address": address,
                "levels": dict(levels),
                "pattern": pattern,
                "rssi": rssi,
            }
        )
        while len(self._manual_inputs) > self.history_limit:
            self._manual_inputs.popleft()

    def set_auto_tune(self, enabled: bool) -> None:
        self._auto_tune_enabled = enabled

    def suggest(
        self,
        *,
        address: str,
        current_levels: dict[str, int],
        rssi: int | None,
        connected: bool,
    ) -> dict[str, Any]:
        recent = [item for item in self._manual_inputs if item["address"] == address][-8:]
        predicted_thrust = current_levels.get("thrust", 0)
        predicted_vibrate = current_levels.get("vibrate", 0)
        if recent:
            predicted_thrust = round(sum(item["levels"].get("thrust", 0) for item in recent) / len(recent))
            predicted_vibrate = round(sum(item["levels"].get("vibrate", 0) for item in recent) / len(recent))

        quality = signal_quality_label(rssi)
        notes: list[str] = []
        suggested_thrust = predicted_thrust
        suggested_vibrate = predicted_vibrate
        suggested_pattern: str | None = None

        if quality == "poor":
            suggested_thrust = min(suggested_thrust, 35)
            suggested_vibrate = min(suggested_vibrate, 35)
            notes.append("Weak BLE link — cap throttle to preserve connection.")
        elif quality == "fair":
            suggested_thrust = min(suggested_thrust, 60)
            suggested_vibrate = min(suggested_vibrate, 60)
            notes.append("Fair signal — moderate throttle recommended.")

        if not connected:
            notes.append("Connect before applying suggestions.")

        pulse_patterns = [item["pattern"] for item in recent if item.get("pattern")]
        if pulse_patterns:
            suggested_pattern = pulse_patterns[-1]
            notes.append(f"Recent pattern preference: {suggested_pattern}.")

        if self._auto_tune_enabled and quality in {"excellent", "good"}:
            suggested_thrust = min(100, suggested_thrust + 5)
            notes.append("Auto-tune raised throttle slightly for strong signal.")

        return {
            "address": address,
            "suggested_levels": {
                "thrust": max(0, min(100, suggested_thrust)),
                "vibrate": max(0, min(100, suggested_vibrate)),
            },
            "suggested_pattern": suggested_pattern,
            "signal_quality": quality,
            "auto_tune_enabled": self._auto_tune_enabled,
            "notes": notes,
            "sample_count": len(recent),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "auto_tune_enabled": self._auto_tune_enabled,
            "manual_sample_count": len(self._manual_inputs),
        }
