import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from wifi_radar.state import Observation, RadarState


def _obs(bssid: str, rssi: int, when: datetime, ssid: str | None = "AP") -> Observation:
    return Observation(bssid=bssid, ssid=ssid, rssi=rssi, channel=6, frequency_mhz=2437, observed_at=when)


class StateTests(unittest.TestCase):
    def test_new_left_and_reentered_events(self) -> None:
        asyncio.run(self._flow())

    async def _flow(self) -> None:
        state = RadarState(stale_after=1, alarm_range_m=2.0)
        now = datetime.now(UTC)

        events = await state.observe(_obs("aa:bb:cc:dd:ee:01", -70, now))
        self.assertEqual(events[0]["type"], "new")

        snapshot = await state.snapshot()
        self.assertEqual(snapshot["present_count"], 1)

        await state.observe(_obs("aa:bb:cc:dd:ee:01", -70, now - timedelta(seconds=5)))
        left = await state.mark_stale()
        self.assertEqual(left[0]["type"], "left")

        events = await state.observe(_obs("aa:bb:cc:dd:ee:01", -68, datetime.now(UTC)))
        self.assertEqual(events[0]["type"], "entered")

    def test_alarm_fires_when_device_approaches(self) -> None:
        asyncio.run(self._alarm_flow())

    async def _alarm_flow(self) -> None:
        # alarm_range 2m -> requires a strong RSSI. Reference is -45 dBm at 1m.
        state = RadarState(stale_after=30, alarm_range_m=2.0)
        now = datetime.now(UTC)

        # Far away: no alarm.
        for i in range(4):
            events = await state.observe(_obs("11:22:33:44:55:66", -85, now + timedelta(seconds=i)))
            self.assertFalse(any(e["type"] == "alarm" for e in events))

        # Approaches to a near-field RSSI (well inside 2m).
        alarm_seen = False
        for i in range(4, 10):
            events = await state.observe(_obs("11:22:33:44:55:66", -40, now + timedelta(seconds=i)))
            if any(e["type"] == "alarm" and e["alarm"] for e in events):
                alarm_seen = True
        self.assertTrue(alarm_seen)

        snapshot = await state.snapshot()
        device = snapshot["devices"][0]
        self.assertTrue(device["in_alarm_zone"])
        self.assertEqual(snapshot["alarm_count"], 1)

    def test_alarm_does_not_refire_while_inside_zone(self) -> None:
        asyncio.run(self._no_refire_flow())

    async def _no_refire_flow(self) -> None:
        state = RadarState(stale_after=30, alarm_range_m=3.0)
        now = datetime.now(UTC)
        alarm_events = 0
        for i in range(12):
            events = await state.observe(_obs("de:ad:be:ef:00:01", -42, now + timedelta(seconds=i)))
            alarm_events += sum(1 for e in events if e["type"] == "alarm")
        self.assertEqual(alarm_events, 1)

    def test_set_alarm_range_clamps_and_resets(self) -> None:
        asyncio.run(self._set_range_flow())

    async def _set_range_flow(self) -> None:
        state = RadarState(alarm_range_m=5.0)
        event = await state.set_alarm_range(200.0)
        self.assertEqual(state.alarm_range_m, 120.0)
        self.assertEqual(event["type"], "config")
        await state.set_alarm_range(0.1)
        self.assertEqual(state.alarm_range_m, 0.5)


if __name__ == "__main__":
    unittest.main()
