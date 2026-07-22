"""Cross-platform Bluetooth runtime helpers for Bleak (Linux BlueZ + macOS Core Bluetooth)."""

from __future__ import annotations

import os
import platform
import re
import sys
from pathlib import Path
from typing import Any

_SYSTEM_DBUS_SOCKETS: tuple[Path, ...] = (
    Path("/run/dbus/system_bus_socket"),
    Path("/var/run/dbus/system_bus_socket"),
)


def host_platform() -> str:
    return platform.system()


def is_linux() -> bool:
    return host_platform() == "Linux"


def is_macos() -> bool:
    return host_platform() == "Darwin"


def bleak_backend_label() -> str:
    if is_macos():
        return "corebluetooth"
    if is_linux():
        return "bluez"
    if host_platform() == "Windows":
        return "winrt"
    return "unknown"


def prepare_ble_runtime() -> None:
    """Apply OS-specific environment tweaks before importing Bleak backends."""
    if is_linux():
        ensure_system_dbus_address()


def ensure_system_dbus_address() -> str | None:
    """
    Bleak on Linux talks to BlueZ over the system D-Bus.

    Some environments expose the socket only under ``/run/dbus`` while
    defaults still point at missing ``/var/run/dbus``, which surfaces as
    ``FileNotFoundError`` during scan startup.
    """
    if not is_linux():
        return os.environ.get("DBUS_SYSTEM_BUS_ADDRESS") or None

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


def bleak_scanner_kwargs() -> dict[str, Any]:
    """
    Platform-tuned kwargs for :class:`bleak.BleakScanner`.

  macOS Sequoia uses Core Bluetooth (not BlueZ). Active scanning is required.
    """
    if is_macos():
        # Do not set service_uuids filter — toys may only expose the Galaku name
        # in some advertisement frames; filtering would hide them on macOS.
        return {
            "scanning_mode": "active",
            "cb": {"use_bdaddr": False},
        }
    return {"scanning_mode": "active"}


def describe_scan_failure(exc: BaseException) -> str:
    """Turn low-level Bleak errors into actionable dashboard text."""
    name = type(exc).__name__
    text = str(exc).strip()
    combined = f"{name}: {text}".lower()

    if is_macos():
        if "not authorized" in combined or "authorization" in combined or "denied" in combined:
            return (
                f"{name}: {text}. "
                "macOS blocked Bluetooth for this app. Open System Settings → Privacy & Security → "
                "Bluetooth and allow Terminal (or your IDE) to use Bluetooth, then restart the app."
            )
        if "bluetooth unavailable" in combined or "powered off" in combined:
            return (
                f"{name}: {text}. "
                "Turn on Bluetooth in System Settings → Bluetooth, then retry."
            )
        if "xpc" in combined or "connection invalid" in combined:
            return (
                f"{name}: {text}. "
                "Core Bluetooth service error — quit and reopen the terminal app, or reboot Bluetooth "
                "(toggle Bluetooth off/on in System Settings)."
            )

    if isinstance(exc, FileNotFoundError) or "no such file or directory" in combined:
        if is_linux() and ensure_system_dbus_address():
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
        if is_linux():
            return (
                f"{name}: {text}. "
                "BlueZ could not talk to a Bluetooth controller — check that an adapter is plugged in "
                "and not blocked (rfkill)."
            )
        return f"{name}: {text}."

    if "org.freedesktop.dbus.error.accessdenied" in combined:
        return f"{name}: {text}. Grant this user permission to use Bluetooth (e.g. ``bluetooth`` group)."

    return f"{name}: {text or 'unknown Bluetooth scan error'}"


def startup_scan_hints(*, demo: bool) -> list[str]:
    if demo:
        return []
    hints: list[str] = []
    if is_macos():
        hints.append(
            f"macOS Core Bluetooth backend ({sys.version.split()[0]}). "
            "Grant Bluetooth permission to Terminal/your IDE on first scan."
        )
        return hints
    if is_linux():
        dbus = ensure_system_dbus_address()
        if dbus is None:
            hints.append("System D-Bus socket not found; live BLE scan will fail until D-Bus is running.")
        if not linux_has_bluetooth_sysfs():
            hints.append(
                "No /sys/class/bluetooth entries — this host has no Bluetooth hardware "
                "(use a machine with an adapter, or run with --demo)."
            )
    return hints


def scan_help_suffix(*, host_platform_name: str) -> str:
    if host_platform_name == "Darwin":
        return (
            "On macOS: System Settings → Privacy & Security → Bluetooth → allow this terminal app. "
            "Keep the toy powered on (flashing light) nearby. The scanner retries automatically."
        )
    return (
        "On Linux: enable Bluetooth and start bluetoothd; this app retries automatically. "
        "Keep the toy powered on (flashing light) within a few meters of the adapter."
    )


def compact_error_for_api(exc: BaseException) -> str:
    """Single-line error string stored on API snapshots."""
    message = describe_scan_failure(exc)
    return re.sub(r"\s+", " ", message).strip()
