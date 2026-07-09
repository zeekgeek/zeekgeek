import unittest

from bt_radar.calibration import (
    estimate_distance_label,
    estimate_distance_meters,
    get_calibration_profile,
    lookup_distance_meters,
    normalize_rssi_for_lookup,
)


class CalibrationTests(unittest.TestCase):
    def test_anchor_point_is_one_meter(self) -> None:
        self.assertAlmostEqual(estimate_distance_meters(-59), 1.0, places=2)

    def test_stronger_signal_is_closer(self) -> None:
        near = estimate_distance_meters(-52)
        far = estimate_distance_meters(-83)
        assert near is not None and far is not None
        self.assertLess(near, far)

    def test_tx_power_adjustment_shifts_lookup(self) -> None:
        profile = get_calibration_profile()
        without_tx = lookup_distance_meters(-67, profile)
        adjusted = normalize_rssi_for_lookup(-20, -12, profile.reference_tx_power_dbm)
        with_strong_tx = lookup_distance_meters(adjusted, profile)
        self.assertAlmostEqual(without_tx, with_strong_tx, places=1)
        self.assertGreater(
            lookup_distance_meters(normalize_rssi_for_lookup(-67, -12, profile.reference_tx_power_dbm), profile),
            without_tx,
        )

    def test_lookup_interpolates_between_points(self) -> None:
        profile = get_calibration_profile()
        between = lookup_distance_meters(-65, profile)
        self.assertGreater(between, 1.4)
        self.assertLess(between, 2.0)

    def test_lookup_clamps_to_profile_bounds(self) -> None:
        profile = get_calibration_profile()
        self.assertEqual(lookup_distance_meters(-20, profile), profile.min_distance_m)
        self.assertEqual(lookup_distance_meters(-120, profile), profile.max_distance_m)

    def test_distance_labels_use_meters(self) -> None:
        self.assertEqual(estimate_distance_label(0.8), "very near")
        self.assertEqual(estimate_distance_label(2.5), "near")
        self.assertEqual(estimate_distance_label(6.0), "mid-range")
        self.assertEqual(estimate_distance_label(25.0), "far/weak")
        self.assertEqual(estimate_distance_label(None), "unknown")


if __name__ == "__main__":
    unittest.main()
