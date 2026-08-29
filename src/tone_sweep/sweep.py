"""Sweep configuration and deterministic frequency calculation."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class SweepConfig:
    low_hz: float = 47.0
    high_hz: float = 65.0
    sweep_seconds: float = 90.0
    max_gain: float = 0.12

    def __post_init__(self) -> None:
        if self.low_hz <= 0:
            raise ValueError("low_hz must be positive")
        if self.high_hz <= self.low_hz:
            raise ValueError("high_hz must be greater than low_hz")
        if self.sweep_seconds < 10:
            raise ValueError("sweep_seconds must be at least 10")
        if not 0 < self.max_gain <= 0.2:
            raise ValueError("max_gain must be between 0 and 0.2")

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def sweep_frequency(elapsed_seconds: float, config: SweepConfig = SweepConfig()) -> float:
    """Return the frequency for a continuous up/down triangular sweep."""
    phase = max(0.0, elapsed_seconds) / config.sweep_seconds
    position = phase % 2.0
    if position > 1.0:
        position = 2.0 - position
    return config.low_hz + (config.high_hz - config.low_hz) * position
