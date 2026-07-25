import unittest

from bt_thrust.protocols import (
    build_command,
    galaku_dual_motor_command,
    galaku_send_bytes,
    galaku_single_motor_command,
    levels_from_pattern,
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

    def test_match_adorime_profile(self) -> None:
        profile = match_device_profile("BGSF")
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.brand, "adorime")
        self.assertTrue(profile.is_dual_motor)

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
