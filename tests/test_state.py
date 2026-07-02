import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from bt_radar.state import (
    Observation,
    RadarState,
    estimate_distance_label,
    estimate_distance_meters,
    movement_label,
    smooth_rssi,
)


class StateTests(unittest.TestCase):
    def test_movement_and_distance_labels(self) -> None:
        self.assertEqual(movement_label([-80, -78]), "collecting")
        self.assertEqual(movement_label([-80, -76, -68]), "approaching")
        self.assertEqual(movement_label([-50, -55, -65]), "departing")
        self.assertEqual(estimate_distance_label(-45), "very near")
        self.assertEqual(estimate_distance_label(-72), "mid-range")
        self.assertEqual(smooth_rssi([-90, -80, -75, -62]), -72)
        self.assertIsNone(smooth_rssi([]))
        self.assertAlmostEqual(estimate_distance_meters(-59), 1.0, places=1)

    def test_state_tracks_new_left_and_reappeared_events(self) -> None:
        asyncio.run(_state_flow())


async def _state_flow() -> None:
    state = RadarState(stale_after=1)
    await state.set_scanner_status(mode="live", status="Scanning live Bluetooth advertisements", is_live=True)
    now = datetime.now(UTC)
    events = await state.observe(
        Observation(
            address="D4:8A:FC:12:34:56",
            name="Keyboard",
            address_type="public",
            manufacturer_id=76,
            rssi=-55,
            observed_at=now,
        )
    )
    assert events[0]["type"] == "new"

    left_events = await state.mark_stale()
    assert left_events == []

    snapshot = await state.snapshot()
    assert snapshot["present_count"] == 1
    assert snapshot["scanner"]["mode"] == "live"
    assert snapshot["scanner"]["is_live"] is True

    await state.observe(
        Observation(
            address="D4:8A:FC:12:34:56",
            name="Keyboard",
            address_type="public",
            manufacturer_id=76,
            rssi=-80,
            observed_at=now - timedelta(seconds=5),
        )
    )
    left_events = await state.mark_stale()
    assert left_events[0]["type"] == "left"

    events = await state.observe(
        Observation(
            address="D4:8A:FC:12:34:56",
            name="Keyboard",
            address_type="public",
            manufacturer_id=76,
            rssi=-52,
            observed_at=datetime.now(UTC),
        )
    )
    assert events[0]["type"] == "entered"


if __name__ == "__main__":
    unittest.main()
