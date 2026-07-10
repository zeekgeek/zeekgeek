import unittest

from wifi_radar.motion import (
    classify_motion,
    distance_label,
    estimate_distance_meters,
    movement_direction,
    smooth_rssi,
)


class MotionTests(unittest.TestCase):
    def test_collecting_when_too_few_samples(self) -> None:
        self.assertEqual(classify_motion([-60, -61]), "collecting")

    def test_flat_signal_is_stationary(self) -> None:
        self.assertEqual(classify_motion([-60, -61, -60, -59, -60, -61, -60, -60]), "stationary")

    def test_trending_signal_is_moving(self) -> None:
        self.assertEqual(classify_motion([-80, -76, -72, -68, -64, -60, -56, -52]), "moving")

    def test_jittery_signal_is_moving(self) -> None:
        self.assertEqual(classify_motion([-80, -60, -82, -58, -84, -62, -79, -59]), "moving")

    def test_movement_direction(self) -> None:
        self.assertEqual(movement_direction([-80, -74, -68, -62, -56]), "approaching")
        self.assertEqual(movement_direction([-56, -62, -68, -74, -80]), "departing")
        self.assertEqual(movement_direction([-60, -61, -60, -59, -60]), "steady")

    def test_distance_estimate_and_label(self) -> None:
        self.assertAlmostEqual(estimate_distance_meters(-45), 1.0, places=1)
        self.assertGreater(estimate_distance_meters(-75), estimate_distance_meters(-55))
        self.assertEqual(distance_label(1.5), "very near")
        self.assertEqual(distance_label(10), "mid-range")
        self.assertEqual(distance_label(None), "unknown")

    def test_smooth_rssi_weights_recent(self) -> None:
        self.assertIsNone(smooth_rssi([]))
        self.assertEqual(smooth_rssi([-90, -80, -75, -62]), -72)


if __name__ == "__main__":
    unittest.main()
