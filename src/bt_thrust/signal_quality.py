"""RSSI statistics and signal-quality labels."""

from __future__ import annotations

from typing import Any

QUALITY_THRESHOLDS: tuple[tuple[str, int], ...] = (
    ("excellent", -50),
    ("good", -65),
    ("fair", -80),
    ("poor", -127),
)


def signal_quality_label(rssi: int | None) -> str:
    if rssi is None:
        return "unknown"
    for label, threshold in QUALITY_THRESHOLDS:
        if rssi >= threshold:
            return label
    return "poor"


def rssi_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "latest": None,
            "average": None,
            "min": None,
            "max": None,
            "quality": "unknown",
        }
    latest = values[-1]
    return {
        "count": len(values),
        "latest": latest,
        "average": round(sum(values) / len(values), 1),
        "min": min(values),
        "max": max(values),
        "quality": signal_quality_label(latest),
    }


def device_type_label(
    *,
    controllable: bool,
    adorime_match: bool,
    galaku_service: bool,
    name: str | None,
) -> str:
    if adorime_match:
        return "adorime_thruster"
    if controllable or galaku_service:
        return "ble_peripheral"
    lowered = (name or "").lower()
    if any(token in lowered for token in ("phone", "iphone", "pixel", "galaxy")):
        return "phone"
    if any(token in lowered for token in ("watch", "band", "fitbit")):
        return "wearable"
    if any(token in lowered for token in ("keyboard", "mouse", "trackpad")):
        return "input_device"
    if any(token in lowered for token in ("speaker", "headphone", "airpod", "buds")):
        return "audio"
    return "unknown"
