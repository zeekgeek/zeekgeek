import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from adorime_control.state import Observation, RadarState, movement_label


class AdorimeStateTests(unittest.TestCase):
    def test_movement_label(self) -> None:
        self.assertEqual(movement_label([-85, -80]), "collecting")
        self.assertEqual(movement_label([-85, -79, -70]), "approaching")
        self.assertEqual(movement_label([-52, -62, -70]), "departing")

    def test_manual_and_ai_control_flow(self) -> None:
        asyncio.run(self._control_flow())

    async def _control_flow(self) -> None:
        state = RadarState(stale_after=2.0)
        now = datetime.now(UTC)
        await state.observe(
            Observation(
                address="A1:42:19:77:33:10",
                name="AdoRime Thrust Pod",
                address_type="random",
                rssi=-58,
                observed_at=now,
            )
        )

        event = await state.set_control_target("A1:42:19:77:33:10")
        self.assertEqual(event["type"], "control-target")

        manual = await state.send_manual_thrust(73, pattern="pulse")
        self.assertEqual(manual["type"], "control-command")
        self.assertEqual(manual["control"]["thrust"], 73)
        self.assertEqual(manual["control"]["source"], "manual")

        await state.configure_ai_thrust(enabled=True, aggressiveness=0.75, min_thrust=20, max_thrust=88)
        ai_event = await state.run_ai_thrust_step()
        self.assertEqual(ai_event["type"], "control-command")
        self.assertEqual(ai_event["control"]["source"], "ai-thrust")
        self.assertGreaterEqual(ai_event["control"]["thrust"], 20)
        self.assertLessEqual(ai_event["control"]["thrust"], 88)

        snapshot = await state.snapshot()
        self.assertEqual(snapshot["control"]["target_address"], "A1:42:19:77:33:10")
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

    def test_idle_command_emits_when_target_leaves(self) -> None:
        asyncio.run(self._idle_flow())

    async def _idle_flow(self) -> None:
        state = RadarState(stale_after=1.0)
        now = datetime.now(UTC)
        target = "A1:42:19:77:33:10"
        await state.observe(
            Observation(
                address=target,
                name="AdoRime Vector",
                address_type="random",
                rssi=-60,
                observed_at=now,
            )
        )
        await state.set_control_target(target)
        await state.configure_ai_thrust(enabled=True, aggressiveness=0.7, min_thrust=10, max_thrust=80)
        await state.run_ai_thrust_step()

        await state.observe(
            Observation(
                address=target,
                name="AdoRime Vector",
                address_type="random",
                rssi=-90,
                observed_at=now - timedelta(seconds=5),
            )
        )
        events = await state.mark_stale()
        idle = [event for event in events if event["type"] == "control-command" and event["control"]["thrust"] == 0]
        self.assertTrue(idle)


if __name__ == "__main__":
    unittest.main()
