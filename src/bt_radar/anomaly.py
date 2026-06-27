"""Heuristics for Bluetooth radar classifications.

The rules in this module intentionally avoid claiming that a device belongs to
any government or law-enforcement agency. Bluetooth metadata is incomplete and
frequently randomized, so the safest output is a confidence-scored observation
that an operator can investigate further.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import pstdev


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Finding:
    code: str
    title: str
    severity: Severity
    detail: str


def is_randomized_address(address: str, address_type: str | None = None) -> bool:
    """Return True when the address appears to be a BLE random/private address."""
    normalized_type = (address_type or "").lower()
    if "random" in normalized_type or "private" in normalized_type:
        return True

    first_octet = _first_octet(address)
    if first_octet is None:
        return False

    # BLE random static/private addresses have the two most significant bits of
    # the first octet set to 11, 10, or 01 depending on subtype. Public OUIs use
    # normal IEEE allocation; this bit test is a heuristic when the scanner does
    # not expose address_type.
    return (first_octet & 0b1100_0000) in {0b0100_0000, 0b1000_0000, 0b1100_0000}


def address_family(address: str, address_type: str | None = None) -> str:
    if is_randomized_address(address, address_type):
        return "rotating/randomized"
    if _first_octet(address) is None:
        return "unknown"
    return "public/common"


def evaluate_device(
    *,
    address: str,
    address_type: str | None,
    name: str | None,
    manufacturer_id: int | None,
    rssi_history: list[int],
    seen_count: int,
    reappear_count: int,
    stale_seconds: float | None,
) -> list[Finding]:
    findings: list[Finding] = []
    display_name = (name or "").strip()

    if is_randomized_address(address, address_type):
        findings.append(
            Finding(
                "randomized-address",
                "Randomized or private Bluetooth address",
                Severity.INFO,
                "The address pattern or scanner metadata suggests BLE address randomization.",
            )
        )

    if not display_name:
        findings.append(
            Finding(
                "no-friendly-name",
                "No advertised friendly name",
                Severity.LOW,
                "The device did not advertise a user-friendly name.",
            )
        )

    if manufacturer_id is None and seen_count > 5:
        findings.append(
            Finding(
                "missing-manufacturer",
                "No manufacturer data after repeated sightings",
                Severity.LOW,
                "Repeated advertisements were observed without manufacturer data.",
            )
        )

    if len(rssi_history) >= 6:
        rssi_span = max(rssi_history) - min(rssi_history)
        rssi_jitter = pstdev(rssi_history)
        if rssi_span >= 35 or rssi_jitter >= 15:
            findings.append(
                Finding(
                    "volatile-signal",
                    "Volatile signal pattern",
                    Severity.MEDIUM,
                    "RSSI changed sharply, which can indicate fast movement, obstruction, or relay effects.",
                )
            )

    if reappear_count >= 3:
        findings.append(
            Finding(
                "repeated-reappearance",
                "Repeated enter/leave pattern",
                Severity.MEDIUM,
                "The device repeatedly disappeared and reappeared during this session.",
            )
        )

    if stale_seconds is not None and stale_seconds < 10 and len(rssi_history) >= 3:
        if rssi_history[-1] - rssi_history[0] >= 18:
            findings.append(
                Finding(
                    "approaching",
                    "Signal strengthening",
                    Severity.INFO,
                    "RSSI is trending stronger; the device may be moving closer.",
                )
            )
        elif rssi_history[0] - rssi_history[-1] >= 18:
            findings.append(
                Finding(
                    "departing",
                    "Signal weakening",
                    Severity.INFO,
                    "RSSI is trending weaker; the device may be moving away.",
                )
            )

    if _looks_like_watchlist_name(display_name):
        findings.append(
            Finding(
                "watchlist-keyword",
                "Name matches local watchlist keyword",
                Severity.HIGH,
                "The advertised name matched a configurable local keyword. Verify before acting.",
            )
        )

    return findings


def _looks_like_watchlist_name(name: str) -> bool:
    if not name:
        return False
    watchlist_terms = {
        "tracker",
        "beacon",
        "bodycam",
        "dashcam",
        "camera",
        "mesh",
        "sensor",
    }
    lower_name = name.lower()
    return any(term in lower_name for term in watchlist_terms)


def _first_octet(address: str) -> int | None:
    parts = address.split(":")
    if len(parts) != 6:
        return None
    try:
        return int(parts[0], 16)
    except ValueError:
        return None
