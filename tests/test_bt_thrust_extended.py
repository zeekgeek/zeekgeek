import asyncio
import io
import json
import unittest

from bt_thrust.ai_assist import ThrusterAdvisor
from bt_thrust.export import export_connection_logs_csv, export_devices_csv, export_snapshot_json
from bt_thrust.signal_quality import device_type_label, rssi_stats, signal_quality_label
from bt_thrust.state import ControllerState, ToyObservation


class SignalQualityTests(unittest.TestCase):
    def test_signal_quality_labels(self) -> None:
        self.assertEqual(signal_quality_label(-45), "excellent")
        self.assertEqual(signal_quality_label(-60), "good")
        self.assertEqual(signal_quality_label(-75), "fair")
        self.assertEqual(signal_quality_label(-90), "poor")

    def test_rssi_stats(self) -> None:
        stats = rssi_stats([-70, -65, -60])
        self.assertEqual(stats["min"], -70)
        self.assertEqual(stats["max"], -60)
        self.assertEqual(stats["latest"], -60)
        self.assertEqual(stats["quality"], "good")

    def test_device_type_label(self) -> None:
        self.assertEqual(
            device_type_label(controllable=True, adorime_match=True, galaku_service=True, name="BGSF"),
            "adorime_thruster",
        )
        self.assertEqual(
            device_type_label(controllable=False, adorime_match=False, galaku_service=False, name="iPhone"),
            "phone",
        )


class ExportTests(unittest.TestCase):
    def test_export_snapshot_json_and_csv(self) -> None:
        snapshot = {
            "toys": [
                {
                    "address": "AA:BB:CC:DD:EE:01",
                    "name": "BGSF",
                    "device_type": "adorime_thruster",
                    "transport": "ble",
                    "rssi": -58,
                    "signal_stats": rssi_stats([-58, -60]),
                    "present": True,
                    "controllable": True,
                    "brand": "adorime",
                    "first_seen": "2026-01-01T00:00:00+00:00",
                    "last_seen": "2026-01-01T00:00:10+00:00",
                    "service_uuids": ["00001000-0000-1000-8000-00805f9b34fb"],
                }
            ]
        }
        payload = export_snapshot_json(snapshot)
        self.assertIn("BGSF", payload)
        csv_payload = export_devices_csv(snapshot)
        self.assertIn("adorime_thruster", csv_payload)

    def test_export_connection_logs_csv(self) -> None:
        logs = export_connection_logs_csv(
            [
                {"at": "t", "type": "connected", "address": "AA", "name": "BGSF", "message": "ok"},
                {"at": "t", "type": "new", "address": "BB", "name": "Phone", "message": "seen"},
            ]
        )
        self.assertIn("connected", logs)
        self.assertNotIn("new", logs)


class AdvisorTests(unittest.TestCase):
    def test_suggest_caps_throttle_on_poor_signal(self) -> None:
        advisor = ThrusterAdvisor()
        advisor.record_manual_input(address="AA", levels={"thrust": 80, "vibrate": 70}, rssi=-55)
        suggestion = advisor.suggest(
            address="AA",
            current_levels={"thrust": 80, "vibrate": 70},
            rssi=-92,
            connected=True,
        )
        self.assertLessEqual(suggestion["suggested_levels"]["thrust"], 35)
        self.assertEqual(suggestion["signal_quality"], "poor")


class ExtendedStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_signal_stats_in_snapshot(self) -> None:
        state = ControllerState()
        await state.observe(ToyObservation(address="AA:BB:CC:DD:EE:01", name="BGSF", rssi=-58))
        await state.observe(ToyObservation(address="AA:BB:CC:DD:EE:01", name="BGSF", rssi=-62))
        toy = (await state.snapshot())["toys"][0]
        self.assertEqual(toy["signal_quality"], "good")
        self.assertEqual(toy["device_type"], "adorime_thruster")
        self.assertIn("average", toy["signal_stats"])

    async def test_scanner_filters_and_gatt_storage(self) -> None:
        state = ControllerState()
        await state.set_scanner_filters(min_rssi=-60)
        await state.observe(ToyObservation(address="AA:BB:CC:DD:EE:01", name="BGSF", rssi=-70))
        await state.observe(ToyObservation(address="AA:BB:CC:DD:EE:02", name="Phone", rssi=-55))
        snapshot = await state.snapshot()
        self.assertEqual(len(snapshot["toys"]), 1)
        event = await state.store_gatt_result(
            "AA:BB:CC:DD:EE:02",
            {"services": [{"uuid": "svc", "characteristics": []}], "error": None},
        )
        self.assertIsNotNone(event)
        self.assertEqual(event["type"], "gatt-deep-scan")

    async def test_classic_device_observation(self) -> None:
        state = ControllerState()
        await state.observe_classic_device(address="AA:BB:CC:DD:EE:99", name="Speaker", device_class="audio")
        toy = (await state.snapshot())["toys"][0]
        self.assertEqual(toy["transport"], "classic")
        self.assertEqual(toy["name"], "Speaker")


if __name__ == "__main__":
    unittest.main()
