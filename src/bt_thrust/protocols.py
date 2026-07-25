"""BLE protocol helpers for Adorime products."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any


KEY_TAB: list[list[int]] = [
    [0, 24, 152, 247, 165, 61, 13, 41, 37, 80, 68, 70],
    [0, 69, 110, 106, 111, 120, 32, 83, 45, 49, 46, 55],
    [0, 101, 120, 32, 84, 111, 121, 115, 10, 142, 157, 163],
    [0, 197, 214, 231, 248, 10, 50, 32, 111, 98, 13, 10],
]


def get_tab_key(row: int, column: int) -> int:
    return KEY_TAB[3 & row][column]


def encrypt(data: list[int]) -> list[int]:
    encrypted = [data[0]]
    for index in range(1, len(data)):
        key = get_tab_key(encrypted[index - 1], index)
        encrypted.append((key ^ data[0] ^ data[index]) + key)
    return encrypted


def galaku_send_bytes(payload: list[int]) -> bytes:
    frame = [35, *payload, sum([35, *payload]) % 256]
    return bytes(value & 0xFF for value in encrypt(frame))


def galaku_single_motor_command(speed: int) -> bytes:
    clamped = max(0, min(100, int(speed)))
    return galaku_send_bytes([90, 0, 0, 1, 49, clamped, 0, 0, 0, 0])


def galaku_dual_motor_command(thrust: int, vibrate: int) -> bytes:
    thrust_clamped = max(0, min(100, int(thrust)))
    vibrate_clamped = max(0, min(100, int(vibrate)))
    return galaku_send_bytes([90, 0, 0, 1, 64, 3, thrust_clamped, vibrate_clamped, 0, 0])


@dataclass(frozen=True)
class MotorProfile:
    id: str
    label: str
    motor_type: str


@dataclass(frozen=True)
class DeviceProfile:
    identifiers: tuple[str, ...]
    name: str
    brand: str
    theme: str
    protocol: str
    motors: tuple[MotorProfile, ...]

    @property
    def is_dual_motor(self) -> bool:
        return len(self.motors) >= 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "brand": self.brand,
            "theme": self.theme,
            "protocol": self.protocol,
            "motors": [
                {"id": motor.id, "label": motor.label, "type": motor.motor_type}
                for motor in self.motors
            ],
        }


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    raw = resources.files("bt_thrust.data").joinpath("device_profiles.json").read_text(encoding="utf-8")
    return json.loads(raw)


def protocol_config(protocol: str) -> dict[str, str]:
    catalog = load_catalog()
    return catalog["protocols"][protocol]


def device_profiles() -> list[DeviceProfile]:
    catalog = load_catalog()
    profiles: list[DeviceProfile] = []
    for item in catalog["devices"]:
        if item.get("brand") != "adorime":
            continue
        motors = tuple(
            MotorProfile(id=motor["id"], label=motor["label"], motor_type=motor["type"])
            for motor in item["motors"]
        )
        profiles.append(
            DeviceProfile(
                identifiers=tuple(item["identifiers"]),
                name=item["name"],
                brand=item["brand"],
                theme=item["theme"],
                protocol=item["protocol"],
                motors=motors,
            )
        )
    return profiles


def match_device_profile(name: str | None) -> DeviceProfile | None:
    if not name:
        return None
    normalized = name.strip()
    for profile in device_profiles():
        for identifier in profile.identifiers:
            if normalized == identifier or normalized.startswith(identifier):
                return profile
    return None


def match_adorime_profile(name: str | None) -> DeviceProfile | None:
    profile = match_device_profile(name)
    if profile is None or profile.brand != "adorime":
        return None
    return profile


def build_command(profile: DeviceProfile, levels: dict[str, int]) -> bytes:
    if profile.protocol == "adorime":
        if profile.is_dual_motor:
            thrust = levels.get(profile.motors[0].id, 0)
            vibrate = levels.get(profile.motors[1].id, 0)
            return galaku_dual_motor_command(thrust, vibrate)
        primary = levels.get(profile.motors[0].id, 0)
        return galaku_single_motor_command(primary)
    raise ValueError(f"Unsupported protocol for Adorime controller: {profile.protocol}")


def _catalog_entries(key: str) -> list[dict[str, Any]]:
    catalog = load_catalog()
    return list(catalog.get(key, []))


def catalog_patterns() -> list[dict[str, Any]]:
    return _catalog_entries("patterns")


def catalog_thrust_modes() -> list[dict[str, Any]]:
    return _catalog_entries("thrust_modes")


def catalog_vibrate_modes() -> list[dict[str, Any]]:
    return _catalog_entries("vibrate_modes")


def catalog_quick_levels() -> list[int]:
    catalog = load_catalog()
    levels = catalog.get("quick_levels", [0, 25, 50, 75, 100])
    return [max(0, min(100, int(level))) for level in levels]


def _steps_from_catalog(pattern_id: str) -> list[dict[str, int]] | None:
    for entry in (
        catalog_patterns()
        + catalog_thrust_modes()
        + catalog_vibrate_modes()
    ):
        if entry.get("id") != pattern_id:
            continue
        steps = entry.get("steps")
        if isinstance(steps, list) and steps:
            return [dict(step) for step in steps]
    return None


def pattern_steps(pattern_id: str) -> list[dict[str, int]]:
    catalog_steps = _steps_from_catalog(pattern_id)
    if catalog_steps is not None:
        return catalog_steps
    if pattern_id == "stop":
        return [{"thrust": 0, "vibrate": 0}]
    return [{"thrust": 0, "vibrate": 0}]


def levels_from_pattern(profile: DeviceProfile, step: dict[str, int]) -> dict[str, int]:
    levels: dict[str, int] = {}
    for motor in profile.motors:
        if motor.id in step:
            levels[motor.id] = step[motor.id]
        elif motor.motor_type in {"oscillate", "thrust"} and "thrust" in step:
            levels[motor.id] = step["thrust"]
        elif motor.motor_type == "vibrate" and "vibrate" in step:
            levels[motor.id] = step["vibrate"]
        else:
            levels[motor.id] = 0
    return levels
