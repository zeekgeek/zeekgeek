"""RSSI-to-distance calibration database and lookup helpers."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any


@dataclass(frozen=True)
class CalibrationPoint:
    rssi_dbm: int
    distance_m: float


@dataclass(frozen=True)
class CalibrationProfile:
    name: str
    description: str
    reference_tx_power_dbm: int
    min_distance_m: float
    max_distance_m: float
    points: tuple[CalibrationPoint, ...]


def _parse_profile(name: str, payload: dict[str, Any]) -> CalibrationProfile:
    raw_points = payload.get("points", [])
    points = tuple(
        CalibrationPoint(rssi_dbm=int(point["rssi_dbm"]), distance_m=float(point["distance_m"]))
        for point in raw_points
    )
    if len(points) < 2:
        raise ValueError(f"Calibration profile {name!r} needs at least two points")
    if any(points[index].rssi_dbm <= points[index + 1].rssi_dbm for index in range(len(points) - 1)):
        raise ValueError(f"Calibration profile {name!r} must be sorted by descending RSSI")

    return CalibrationProfile(
        name=name,
        description=str(payload.get("description", "")),
        reference_tx_power_dbm=int(payload.get("reference_tx_power_dbm", -59)),
        min_distance_m=float(payload.get("min_distance_m", 0.2)),
        max_distance_m=float(payload.get("max_distance_m", 80.0)),
        points=points,
    )


@lru_cache(maxsize=1)
def load_calibration_database() -> dict[str, CalibrationProfile]:
    with resources.files("bt_radar.data").joinpath("rssi_distance.json").open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    profiles = {
        name: _parse_profile(name, profile_payload)
        for name, profile_payload in payload.get("profiles", {}).items()
    }
    if not profiles:
        raise ValueError("Calibration database must define at least one profile")
    return profiles


def get_calibration_profile(name: str | None = None) -> CalibrationProfile:
    profiles = load_calibration_database()
    if name is None:
        with resources.files("bt_radar.data").joinpath("rssi_distance.json").open("r", encoding="utf-8") as handle:
            default_name = json.load(handle).get("default_profile", "default")
        name = default_name
    try:
        return profiles[name]
    except KeyError as exc:
        raise KeyError(f"Unknown calibration profile: {name!r}") from exc


def normalize_rssi_for_lookup(
    rssi: int,
    tx_power: int | None,
    reference_tx_power_dbm: int,
) -> int:
    """Map measured RSSI onto the reference calibration scale."""
    if tx_power is None:
        return rssi
    return rssi + (reference_tx_power_dbm - tx_power)


def lookup_distance_meters(rssi: int, profile: CalibrationProfile) -> float:
    """Interpolate distance from a calibration table using log-space blending."""
    points = profile.points
    strongest = points[0]
    weakest = points[-1]

    if rssi >= strongest.rssi_dbm:
        return profile.min_distance_m
    if rssi <= weakest.rssi_dbm:
        return profile.max_distance_m

    for index in range(len(points) - 1):
        upper = points[index]
        lower = points[index + 1]
        if lower.rssi_dbm <= rssi <= upper.rssi_dbm:
            if upper.rssi_dbm == lower.rssi_dbm:
                return upper.distance_m
            ratio = (rssi - upper.rssi_dbm) / (lower.rssi_dbm - upper.rssi_dbm)
            log_upper = math.log10(upper.distance_m)
            log_lower = math.log10(lower.distance_m)
            distance = 10 ** (log_upper + ratio * (log_lower - log_upper))
            return round(max(profile.min_distance_m, min(distance, profile.max_distance_m)), 2)

    return profile.max_distance_m


def estimate_distance_meters(
    rssi: int | None,
    tx_power: int | None = None,
    *,
    profile_name: str | None = None,
) -> float | None:
    """Estimate distance from smoothed RSSI using the calibration database."""
    if rssi is None:
        return None

    profile = get_calibration_profile(profile_name)
    adjusted_rssi = normalize_rssi_for_lookup(rssi, tx_power, profile.reference_tx_power_dbm)
    return lookup_distance_meters(adjusted_rssi, profile)


def estimate_distance_label(distance_m: float | None) -> str:
    if distance_m is None:
        return "unknown"
    if distance_m <= 1.0:
        return "very near"
    if distance_m <= 3.0:
        return "near"
    if distance_m <= 10.0:
        return "mid-range"
    return "far/weak"


def calibration_profile_payload(profile_name: str | None = None) -> dict[str, Any]:
    """Serialize a calibration profile for the dashboard/API."""
    profile = get_calibration_profile(profile_name)
    return {
        "name": profile.name,
        "description": profile.description,
        "reference_tx_power_dbm": profile.reference_tx_power_dbm,
        "min_distance_m": profile.min_distance_m,
        "max_distance_m": profile.max_distance_m,
        "points": [
            {"rssi_dbm": point.rssi_dbm, "distance_m": point.distance_m}
            for point in profile.points
        ],
    }
