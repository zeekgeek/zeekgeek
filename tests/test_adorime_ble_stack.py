import unittest

from adorime_control.ble_stack import (
    assess_bluetooth_capability,
    bleak_scanner_kwargs,
    compact_error_for_api,
    describe_scan_failure,
    ensure_system_dbus_address,
    is_linux,
    is_macos,
    live_scan_blocked_message,
)


class BleStackTests(unittest.TestCase):
    def test_ensure_system_dbus_sets_env_when_socket_exists(self) -> None:
        import os
        from pathlib import Path

        if not Path("/run/dbus/system_bus_socket").exists():
            self.skipTest("no system dbus socket in test environment")
        old = os.environ.pop("DBUS_SYSTEM_BUS_ADDRESS", None)
        try:
            address = ensure_system_dbus_address()
            self.assertIsNotNone(address)
            self.assertTrue(address.startswith("unix:path="))
            self.assertEqual(os.environ.get("DBUS_SYSTEM_BUS_ADDRESS"), address)
        finally:
            if old is None:
                os.environ.pop("DBUS_SYSTEM_BUS_ADDRESS", None)
            else:
                os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = old

    def test_describe_file_not_found(self) -> None:
        message = describe_scan_failure(FileNotFoundError(2, "No such file or directory"))
        self.assertIn("DBUS", message)

    def test_describe_missing_bluez(self) -> None:
        exc = Exception("[org.freedesktop.DBus.Error.ServiceUnknown] org.bluez was not provided")
        message = describe_scan_failure(exc)
        self.assertIn("BlueZ", message)

    def test_linux_without_sysfs_is_not_capable(self) -> None:
        if not is_linux():
            self.skipTest("Linux-only")
        assessment = assess_bluetooth_capability()
        if assessment["capable"]:
            self.skipTest("this host has Bluetooth hardware")
        self.assertFalse(assessment["capable"])
        self.assertIn("Mac", assessment["fix"] or "")
        blocked = live_scan_blocked_message()
        self.assertIsNotNone(blocked)
        self.assertIn("Mac", blocked or "")

    def test_macos_scanner_kwargs_active(self) -> None:
        if not is_macos():
            self.skipTest("macOS-only")
        kwargs = bleak_scanner_kwargs()
        self.assertEqual(kwargs.get("scanning_mode"), "active")

    def test_describe_macos_permission(self) -> None:
        exc = Exception("Bluetooth permission denied: not authorized")
        message = describe_scan_failure(exc)
        if is_macos():
            self.assertIn("Privacy & Security", message)
        else:
            self.assertIn("permission denied", message.lower())

    def test_compact_error_single_line(self) -> None:
        text = compact_error_for_api(Exception("line one\nline two"))
        self.assertNotIn("\n", text)


if __name__ == "__main__":
    unittest.main()
