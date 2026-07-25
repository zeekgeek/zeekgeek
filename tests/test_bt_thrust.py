import asyncio
import unittest

from bt_thrust.protocols import (
    GALAKU_SERVICE_UUID,
    build_command,
    catalog_quick_levels,
    catalog_thrust_modes,
    catalog_vibrate_modes,
    galaku_dual_motor_command,
    galaku_send_bytes,
    galaku_single_motor_command,
    levels_from_pattern,
    match_adorime_profile,
    match_device_profile,
    pattern_steps,
)
from bt_thrust.state import ControllerState, ToyObservation


class ProtocolTests(unittest.TestCase):
    def test_galaku_single_motor_command_is_stable(self) -> None:
        payload = galaku_single_motor_command(50)
        self.assertIsInstance(payload, bytes)
        self.assertGreater(len(payload), 4)

    def test_galaku_dual_motor_command_is_stable(self) -> None:
        payload = galaku_dual_motor_command(60, 40)
        self.assertIsInstance(payload, bytes)
        self.assertNotEqual(payload, galaku_single_motor_command(60))

    def test_galaku_send_bytes_checksum(self) -> None:
        payload = galaku_send_bytes([90, 0, 0, 1, 49, 10, 0, 0, 0, 0])
        self.assertEqual(len(payload), 12)

    def test_non_adorime_profile_is_ignored(self) -> None:
        self.assertIsNone(match_device_profile("G312"))
        self.assertIsNone(match_adorime_profile("G312"))

    def test_match_adorime_profile(self) -> None:
        profile = match_device_profile("BGSF")
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.brand, "adorime")
        self.assertTrue(profile.is_dual_motor)

    def test_match_adorime_profile_is_case_insensitive(self) -> None:
        profile = match_device_profile("bgsf")
        self.assertIsNotNone(profile)

    def test_galaku_service_enables_generic_thruster_profile(self) -> None:
        profile = match_adorime_profile(
            None,
            service_uuids=[GALAKU_SERVICE_UUID],
        )
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertTrue(profile.is_dual_motor)
        self.assertIn("thrust", [motor.id for motor in profile.motors])

    def test_build_command_for_dual_motor(self) -> None:
        profile = match_device_profile("SN80")
        self.assertIsNotNone(profile)
        assert profile is not None
        command = build_command(profile, {"thrust": 70, "vibrate": 30})
        self.assertEqual(command, galaku_dual_motor_command(70, 30))

    def test_pattern_levels_map_to_motors(self) -> None:
        profile = match_device_profile("AX05")
        self.assertIsNotNone(profile)
        assert profile is not None
        levels = levels_from_pattern(profile, pattern_steps("pulse")[1])
        self.assertEqual(levels["thrust"], 55)
        self.assertEqual(levels["vibrate"], 45)

    def test_catalog_includes_adorime_modes(self) -> None:
        self.assertEqual(len(catalog_thrust_modes()), 9)
        self.assertEqual(len(catalog_vibrate_modes()), 10)
        self.assertEqual(catalog_quick_levels(), [0, 25, 50, 75, 100])
        self.assertEqual(len(pattern_steps("thrust-3")), 4)
        self.assertEqual(pattern_steps("vibe-10")[0]["vibrate"], 100)


class StateTests(unittest.IsolatedAsyncioTestCase):
    async def test_observe_and_snapshot(self) -> None:
        state = ControllerState(stale_after=5)
        await state.observe(
            ToyObservation(address="AA:BB:CC:DD:EE:01", name="BGSF", rssi=-58)
        )
        snapshot = await state.snapshot()
        self.assertEqual(snapshot["scanner_mode"], "live")
        self.assertEqual(snapshot["toy_count"], 1)
        self.assertEqual(snapshot["toys"][0]["brand"], "adorime")
        self.assertTrue(snapshot["toys"][0]["controllable"])
        self.assertIn("thrust", snapshot["toys"][0]["levels"])
        self.assertIn("movement", snapshot["toys"][0])
        self.assertEqual(len(snapshot["thrust_modes"]), 9)
        self.assertEqual(len(snapshot["vibrate_modes"]), 10)

    async def test_observe_tracks_all_bluetooth_devices(self) -> None:
        state = ControllerState()
        await state.observe(
            ToyObservation(address="AA:BB:CC:DD:EE:02", name="Keyboard", rssi=-64)
        )
        snapshot = await state.snapshot()
        self.assertEqual(snapshot["device_count"], 1)
        self.assertFalse(snapshot["toys"][0]["controllable"])
        self.assertEqual(snapshot["adorime_count"], 0)

    async def test_observe_includes_manufacturer_and_uuid_fields(self) -> None:
        state = ControllerState()
        await state.observe(
            ToyObservation(
                address="AA:BB:CC:DD:EE:07",
                name="BGSF",
                rssi=-58,
                service_uuids=["00001000-0000-1000-8000-00805f9b34fb"],
                manufacturer_id=0x004C,
                tx_power=-12,
                details={
                    "local_name": "BGSF",
                    "manufacturer_data": [
                        {"company_hex": "0x004c", "data_hex": "010203", "data_length": 3}
                    ],
                    "service_data": {"0000180f-0000-1000-8000-00805f9b34fb": "64"},
                    "is_connectable": True,
                },
            )
        )
        snapshot = await state.snapshot()
        toy = snapshot["toys"][0]
        self.assertEqual(toy["local_name"], "BGSF")
        self.assertTrue(toy["galaku_service"])
        self.assertEqual(toy["control_uuids"]["service_uuid"], "00001000-0000-1000-8000-00805f9b34fb")
        self.assertEqual(len(toy["manufacturer_data"]), 1)
        self.assertEqual(toy["details"]["service_data"]["0000180f-0000-1000-8000-00805f9b34fb"], "64")

    async def test_scanner_pause_and_clear_stale(self) -> None:
        state = ControllerState(stale_after=1)
        await state.observe(ToyObservation(address="AA:BB:CC:DD:EE:04", name="BGSF", rssi=-58))
        await state.observe(ToyObservation(address="AA:BB:CC:DD:EE:05", name="Phone", rssi=-70))
        await state.set_scanner_paused(True)
        blocked = await state.observe(
            ToyObservation(address="AA:BB:CC:DD:EE:06", name="Speaker", rssi=-72)
        )
        self.assertEqual(blocked, [])
        snapshot = await state.snapshot()
        self.assertTrue(snapshot["scanner"]["paused"])
        self.assertEqual(snapshot["device_count"], 2)
        await state.mark_stale()
        await asyncio.sleep(1.1)
        await state.mark_stale()
        removed = await state.clear_stale_devices()
        self.assertGreaterEqual(removed, 1)

    async def test_deep_scan_sets_scanner_state(self) -> None:
        state = ControllerState()
        await state.set_scanner_paused(True)
        event = await state.trigger_deep_scan(15)
        snapshot = await state.snapshot()
        self.assertEqual(event["type"], "scanner-deep-scan")
        self.assertFalse(snapshot["scanner"]["paused"])
        self.assertTrue(snapshot["scanner"]["deep_scan_active"])
        self.assertIsNotNone(snapshot["scanner"]["deep_scan_until"])

    async def test_set_levels_merges_partial_updates(self) -> None:
        state = ControllerState()
        address = "AA:BB:CC:DD:EE:03"
        await state.observe(ToyObservation(address=address, name="BGSF", rssi=-58))
        await state.set_connection(address, True)
        await state.set_levels(address, {"thrust": 55, "vibrate": 20})
        await state.set_levels(address, {"thrust": 70})
        snapshot = await state.snapshot()
        levels = snapshot["toys"][0]["levels"]
        self.assertEqual(levels["thrust"], 70)
        self.assertEqual(levels["vibrate"], 20)


if __name__ == "__main__":
    unittest.main()
