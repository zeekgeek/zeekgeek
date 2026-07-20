import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from adorime_control.protocol import (
    encode_galaku_single,
    is_adorime_candidate,
    classify_protocol,
    match_reason,
    match_tier,
    GALAKU_SERVICE_UUID,
)
from adorime_control.state import Observation, RadarState, movement_label


class AdorimeStateTests(unittest.TestCase):
    def test_movement_label(self) -> None:
        self.assertEqual(movement_label([-85, -80]), "collecting")
        self.assertEqual(movement_label([-85, -79, -70]), "approaching")
        self.assertEqual(movement_label([-52, -62, -70]), "departing")

    def test_galaku_name_and_service_detection(self) -> None:
        self.assertTrue(is_adorime_candidate("BGSF", None))
        self.assertTrue(is_adorime_candidate(None, [GALAKU_SERVICE_UUID]))
        self.assertTrue(is_adorime_candidate("ZX99", None))  # heuristic short code
        self.assertFalse(is_adorime_candidate("Keyboard", None))
        self.assertFalse(is_adorime_candidate("AirPods", None))
        self.assertEqual(classify_protocol([GALAKU_SERVICE_UUID], "BGSF"), "galaku")
        self.assertEqual(classify_protocol(None, "QD48"), "galaku")
        self.assertEqual(classify_protocol(None, "ZX99"), "galaku")
        self.assertEqual(match_tier("BGSF", None), "known")
        self.assertEqual(match_tier("ZX99", None), "probable")
        self.assertEqual(match_tier("Keyboard", None), "none")
        self.assertEqual(match_reason("ZX99", None), "galaku-heuristic")

    def test_galaku_command_encoding_is_stable(self) -> None:
        payload = encode_galaku_single(55)
        self.assertIsInstance(payload, (bytes, bytearray))
        self.assertGreaterEqual(len(payload), 8)
        # Wire frames are encrypted; re-encoding the same speed must be deterministic.
        self.assertEqual(payload, encode_galaku_single(55))
        self.assertNotEqual(encode_galaku_single(0), encode_galaku_single(100))

    def test_manual_and_ai_control_flow(self) -> None:
        asyncio.run(self._control_flow())

    async def _control_flow(self) -> None:
        state = RadarState(stale_after=2.0)
        await state.set_scan_status(mode="demo", error=None)
        now = datetime.now(UTC)
        await state.observe(
            Observation(
                address="A1:42:19:77:33:10",
                name="BGSF",
                address_type="random",
                rssi=-58,
                service_uuids=[GALAKU_SERVICE_UUID],
                observed_at=now,
            )
        )

        event = await state.set_control_target("A1:42:19:77:33:10")
        self.assertEqual(event["type"], "control-target")

        manual = await state.send_manual_thrust(73, pattern="pulse")
        self.assertEqual(manual["type"], "control-command")
        self.assertEqual(manual["control"]["thrust"], 73)
        self.assertEqual(manual["control"]["source"], "manual")
        self.assertEqual(manual["control"]["wire"]["mode"], "demo")

        await state.configure_ai_thrust(enabled=True, aggressiveness=0.75, min_thrust=20, max_thrust=88)
        ai_event = await state.run_ai_thrust_step()
        self.assertEqual(ai_event["type"], "control-command")
        self.assertEqual(ai_event["control"]["source"], "ai-thrust")
        self.assertGreaterEqual(ai_event["control"]["thrust"], 20)
        self.assertLessEqual(ai_event["control"]["thrust"], 88)

        snapshot = await state.snapshot()
        self.assertEqual(snapshot["control"]["target_address"], "A1:42:19:77:33:10")
        self.assertEqual(snapshot["control"]["target_name"], "Adorime Male Masturbator")
        self.assertTrue(snapshot["control"]["history"])

    def test_non_adorime_target_is_rejected(self) -> None:
        asyncio.run(self._target_reject_flow())

    async def _target_reject_flow(self) -> None:
        state = RadarState()
        await state.observe(
            Observation(
                address="D4:8A:FC:12:34:56",
                name="Keyboard",
                address_type="public",
                rssi=-70,
                observed_at=datetime.now(UTC),
            )
        )
        with self.assertRaises(ValueError):
            await state.set_control_target("D4:8A:FC:12:34:56")

    def test_probable_heuristic_target_is_accepted(self) -> None:
        asyncio.run(self._probable_target_flow())

    async def _probable_target_flow(self) -> None:
        state = RadarState()
        await state.observe(
            Observation(
                address="CE:11:22:33:44:55",
                name="ZX99",
                address_type="random",
                rssi=-65,
                observed_at=datetime.now(UTC),
            )
        )
        event = await state.set_control_target("CE:11:22:33:44:55")
        self.assertEqual(event["type"], "control-target")
        snapshot = await state.snapshot()
        self.assertEqual(snapshot["candidate_count"], 1)
        nearby = snapshot["control"]["nearby_devices"]
        self.assertGreaterEqual(len(nearby), 1)
        zx = next(item for item in nearby if item["address"] == "CE:11:22:33:44:55")
        self.assertEqual(zx["match_tier"], "probable")
        self.assertTrue(zx["controllable"])
        # Keyboard-like noise is listed nearby but not controllable.
        await state.observe(
            Observation(
                address="D4:8A:FC:12:34:56",
                name="Keyboard",
                address_type="public",
                rssi=-70,
                observed_at=datetime.now(UTC),
            )
        )
        snapshot = await state.snapshot()
        kb = next(item for item in snapshot["control"]["nearby_devices"] if item["address"] == "D4:8A:FC:12:34:56")
        self.assertEqual(kb["match_tier"], "none")
        self.assertFalse(kb["controllable"])
        # Probable toys sort above unrelated BLE noise when both present.
        addresses = [item["address"] for item in snapshot["devices"] if item["present"]]
        self.assertLess(addresses.index("CE:11:22:33:44:55"), addresses.index("D4:8A:FC:12:34:56"))

    def test_idle_command_emits_when_target_leaves(self) -> None:
        asyncio.run(self._idle_flow())

    async def _idle_flow(self) -> None:
        state = RadarState(stale_after=1.0)
        await state.set_scan_status(mode="demo", error=None)
        now = datetime.now(UTC)
        target = "A1:42:19:77:33:10"
        await state.observe(
            Observation(
                address=target,
                name="QD48",
                address_type="random",
                rssi=-60,
                service_uuids=[GALAKU_SERVICE_UUID],
                observed_at=now,
            )
        )
        await state.set_control_target(target)
        await state.configure_ai_thrust(enabled=True, aggressiveness=0.7, min_thrust=10, max_thrust=80)
        await state.run_ai_thrust_step()

        await state.observe(
            Observation(
                address=target,
                name="QD48",
                address_type="random",
                rssi=-90,
                service_uuids=[GALAKU_SERVICE_UUID],
                observed_at=now - timedelta(seconds=5),
            )
        )
        events = await state.mark_stale()
        idle = [event for event in events if event["type"] == "control-command" and event["control"]["thrust"] == 0]
        self.assertTrue(idle)

    def test_hiding_method_assessment_detects_randomized_sparse_broadcast(self) -> None:
        asyncio.run(self._hiding_assessment_flow())

    async def _hiding_assessment_flow(self) -> None:
        state = RadarState(stale_after=3.0)
        now = datetime.now(UTC)
        address = "C1:AA:11:22:33:44"
        for delta, rssi in [(-12, -78), (-11, -76), (-6, -73), (-4, -71)]:
            await state.observe(
                Observation(
                    address=address,
                    name="BGSF",
                    address_type="random",
                    rssi=rssi,
                    service_uuids=[GALAKU_SERVICE_UUID],
                    observed_at=now + timedelta(seconds=delta),
                )
            )
        await state.mark_stale()
        await state.observe(
            Observation(
                address=address,
                name="BGSF",
                address_type="random",
                rssi=-70,
                service_uuids=[GALAKU_SERVICE_UUID],
                observed_at=now + timedelta(seconds=9),
            )
        )

        snapshot = await state.snapshot()
        device = next(item for item in snapshot["devices"] if item["address"] == address)
        method_codes = {method["method"] for method in device["hiding_methods"]}
        self.assertIn("private-address-randomization", method_codes)
        self.assertIn("low-duty-cycle-advertising", method_codes)
        self.assertIn("opaque-local-name", method_codes)
        self.assertIn(device["hiding_confidence"], {"medium", "high"})
        self.assertGreaterEqual(device["reappear_count"], 1)

    def test_live_manual_command_uses_gatt_writer(self) -> None:
        asyncio.run(self._live_write_flow())

    async def _live_write_flow(self) -> None:
        state = RadarState(stale_after=2.0)
        await state.set_scan_status(mode="live", error=None)
        await state.observe(
            Observation(
                address="AA:BB:CC:DD:EE:01",
                name="BGSF",
                address_type="random",
                rssi=-50,
                service_uuids=[GALAKU_SERVICE_UUID],
                observed_at=datetime.now(UTC),
            )
        )
        await state.set_control_target("AA:BB:CC:DD:EE:01")

        with (
            patch.object(state.connections, "is_connected", return_value=True),
            patch.object(
                state.connections,
                "send_thrust",
                new=AsyncMock(return_value={"bytes_hex": "aabb", "protocol": "galaku", "thrust": 40}),
            ) as send_mock,
        ):
            event = await state.send_manual_thrust(40, pattern="steady")

        send_mock.assert_awaited_once()
        self.assertEqual(event["control"]["wire"]["protocol"], "galaku")
        self.assertEqual(event["control"]["wire"]["bytes_hex"], "aabb")


if __name__ == "__main__":
    unittest.main()
