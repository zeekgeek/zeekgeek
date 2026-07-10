"""Motion classification and distance estimation for WiFi targets.

A WiFi device is tracked purely through its received signal strength (RSSI)
over time. A target that is not moving produces a relatively flat RSSI series;
a moving target produces a series that either trends (getting closer/farther)
or jitters well beyond normal measurement noise. These heuristics are coarse:
multipath reflection, walls, antenna orientation, and transmit-power changes
all distort RSSI, so treat the labels as hints rather than measurements.
"""

from __future__ import annotations

from statistics import fmean, pstdev

STATIONARY = "stationary"
MOVING = "moving"
COLLECTING = "collecting"

APPROACHING = "approaching"
DEPARTING = "departing"
STEADY = "steady"

# RSSI at 1 metre for a typical WiFi radio and an indoor path-loss exponent.
REFERENCE_RSSI_AT_1M = -45
PATH_LOSS_EXPONENT = 2.7

# A moving target's recent signal either drifts by more than this many dBm or
# jitters with a standard deviation above this many dBm.
MOTION_TREND_DBM = 6.0
MOTION_JITTER_DBM = 4.0
MOTION_WINDOW = 8
MIN_SAMPLES = 4


def classify_motion(
    rssi_history: list[int],
    *,
    window: int = MOTION_WINDOW,
    trend_dbm: float = MOTION_TREND_DBM,
    jitter_dbm: float = MOTION_JITTER_DBM,
    min_samples: int = MIN_SAMPLES,
) -> str:
    """Label a device ``stationary``, ``moving`` or ``collecting``."""
    if len(rssi_history) < min_samples:
        return COLLECTING

    recent = rssi_history[-window:]
    jitter = pstdev(recent) if len(recent) > 1 else 0.0
    trend = abs(_trend(recent))

    if trend >= trend_dbm or jitter >= jitter_dbm:
        return MOVING
    return STATIONARY


def movement_direction(rssi_history: list[int], *, window: int = MOTION_WINDOW) -> str:
    """Describe whether a device is approaching, departing or steady."""
    if len(rssi_history) < 3:
        return STEADY
    trend = _trend(rssi_history[-window:])
    if trend >= 4.0:
        return APPROACHING
    if trend <= -4.0:
        return DEPARTING
    return STEADY


def estimate_distance_meters(rssi: int | None, reference_rssi: int = REFERENCE_RSSI_AT_1M) -> float | None:
    """Approximate distance in metres from RSSI via log-distance path loss."""
    if rssi is None:
        return None
    distance = 10 ** ((reference_rssi - rssi) / (10 * PATH_LOSS_EXPONENT))
    return round(max(0.2, min(distance, 120.0)), 2)


def distance_label(distance_m: float | None) -> str:
    if distance_m is None:
        return "unknown"
    if distance_m <= 2:
        return "very near"
    if distance_m <= 6:
        return "near"
    if distance_m <= 15:
        return "mid-range"
    return "far/weak"


def smooth_rssi(rssi_history: list[int], window: int = 6) -> int | None:
    """Weighted moving average that favours the most recent samples."""
    if not rssi_history:
        return None
    tail = rssi_history[-window:]
    weighted_total = 0.0
    weight_sum = 0.0
    for index, rssi in enumerate(tail, start=1):
        weighted_total += rssi * index
        weight_sum += index
    return int(round(weighted_total / weight_sum))


def _trend(values: list[int]) -> float:
    """Least-squares slope over the sample index, scaled to the full window.

    A positive result means RSSI is rising (target getting closer). The value
    is expressed as the total dBm change across the window so it can be
    compared against a dBm threshold directly.
    """
    count = len(values)
    if count < 2:
        return 0.0
    xs = list(range(count))
    mean_x = fmean(xs)
    mean_y = fmean(values)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    slope = numerator / denominator
    return slope * (count - 1)
