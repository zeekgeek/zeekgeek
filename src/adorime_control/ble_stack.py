"""Linux Bluetooth / BlueZ environment helpers for Bleak."""

from __future__ import annotations

import os
import re
from pathlib import Path

_SYSTEM_DBUS_SOCKETS: tuple[Path, ...] = (
    Path("/run/dbus/system_bus_socket"),
    Path("/var/run/dbus/system_bus_socket"),
)


def ensure_system_dbus_address() -> str | None:
    """
    Bleak on Linux talks to BlueZ over the system D-Bus.

    Some environments expose the socket only under ``/run/dbus`` while
    defaults still point at missing ``/var/run/dbus``, which surfaces as
    ``FileNotFoundError`` during scan startup.
    """
    existing = os.environ.get("DBUS_SYSTEM_BUS_ADDRESS", "").strip()
    if existing:
        return existing

    for candidate in _SYSTEM_DBUS_SOCKETS:
        if candidate.exists():
            address = f"unix:path={candidate}"
            os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = address
            return address
    return None


def linux_has_bluetooth_sysfs() -> bool:
    return Path("/sys/class/bluetooth").is_dir()


def describe_scan_failure(exc: BaseException) -> str:
    """Turn low-level Bleak/BlueZ errors into actionable dashboard text."""
    name = type(exc).__name__
    text = str(exc).strip()
    combined = f"{name}: {text}".lower()

    if isinstance(exc, FileNotFoundError) or "no such file or directory" in combined:
        if ensure_system_dbus_address():
            return (
                f"{name}: {text or 'D-Bus socket missing'}. "
                "Set DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/dbus/system_bus_socket "
                "(the app tries this automatically on startup)."
            )
        return (
            f"{name}: {text or 'D-Bus system bus unavailable'}. "
            "Start the system D-Bus daemon or set DBUS_SYSTEM_BUS_ADDRESS."
        )

    if "org.bluez" in combined and ("servicenotprovided" in combined or "was not provided" in combined):
        return (
            f"{name}: {text}. "
            "BlueZ is not running. On Linux install ``bluez`` and start ``bluetoothd`` "
            "(``sudo systemctl start bluetooth``)."
        )

    if "management interface" in combined or "adapter handling" in combined:
        return (
            f"{name}: {text}. "
            "No Bluetooth adapter is available to the OS (common on cloud VMs and containers)."
        )

    if "spawn.childexited" in combined or "launch helper exited" in combined:
        return (
            f"{name}: {text}. "
            "BlueZ could not talk to a Bluetooth controller — check that an adapter is plugged in "
            "and not blocked (rfkill)."
        )

    if "org.freedesktop.dbus.error.accessdenied" in combined:
        return f"{name}: {text}. Grant this user permission to use Bluetooth (e.g. ``bluetooth`` group)."

    return f"{name}: {text or 'unknown Bluetooth scan error'}"


def startup_scan_hints(*, demo: bool) -> list[str]:
    if demo:
        return []
    hints: list[str] = []
    dbus = ensure_system_dbus_address()
    if dbus is None:
        hints.append("System D-Bus socket not found; live BLE scan will fail until D-Bus is running.")
    if not linux_has_bluetooth_sysfs():
        hints.append(
            "No /sys/class/bluetooth entries — this host has no Bluetooth hardware "
            "(use a machine with an adapter, or run with --demo)."
        )
    return hints


def compact_error_for_api(exc: BaseException) -> str:
    """Single-line error string stored on API snapshots."""
    message = describe_scan_failure(exc)
    return re.sub(r"\s+", " ", message).strip()
