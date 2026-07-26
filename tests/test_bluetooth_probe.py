import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bt_thrust.bluetooth_probe import AdapterProbeResult, probe_adapter
from bt_thrust.scanner_runner import ScannerRunner
from bt_thrust.state import ControllerState


class BluetoothProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_reports_unavailable_when_bleak_fails(self) -> None:
        with patch("bleak.BleakScanner", side_effect=FileNotFoundError("no adapter")):
            result = await probe_adapter(scan_seconds=0.1)
        self.assertFalse(result.available)
        self.assertIn("FileNotFoundError", result.error or "")

    async def test_probe_reports_available_when_scan_succeeds(self) -> None:
        class FakeScanner:
            backend_id = "bluez"

            async def start(self) -> None:
                return None

            async def stop(self) -> None:
                return None

            @property
            def discovered_devices_and_advertisement_data(self) -> dict:
                return {"aa:bb:cc:dd:ee:01": (object(), object())}

        with patch("bleak.BleakScanner", return_value=FakeScanner()):
            result = await probe_adapter(scan_seconds=0.1)
        self.assertTrue(result.available)
        self.assertEqual(result.device_count, 1)


class ScannerRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_refuses_live_when_no_adapter(self) -> None:
        state = ControllerState()
        runner = ScannerRunner(state=state)
        with patch(
            "bt_thrust.scanner_runner.probe_adapter",
            AsyncMock(
                return_value=AdapterProbeResult(
                    available=False,
                    adapter_name=None,
                    backend=None,
                    device_count=0,
                    error="FileNotFoundError: no adapter",
                    details={},
                )
            ),
        ):
            diagnostics = await runner.restart(demo=False)
        snapshot = await state.snapshot()
        self.assertFalse(diagnostics["probe"]["available"])
        self.assertEqual(snapshot["scanner"]["mode"], "off")
        self.assertIsNotNone(snapshot["scanner"]["error"])


if __name__ == "__main__":
    unittest.main()
