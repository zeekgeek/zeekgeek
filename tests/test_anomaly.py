import unittest

from bt_radar.anomaly import Severity, address_family, evaluate_device, is_randomized_address


class AnomalyTests(unittest.TestCase):
    def test_randomized_address_detection_uses_address_type(self) -> None:
        self.assertTrue(is_randomized_address("00:11:22:33:44:55", "random"))
        self.assertEqual(address_family("00:11:22:33:44:55", "public"), "public/common")

    def test_randomized_address_detection_uses_ble_bit_pattern(self) -> None:
        self.assertTrue(is_randomized_address("C1:44:09:33:71:B8", None))
        self.assertFalse(is_randomized_address("04:44:09:33:71:B8", None))

    def test_evaluate_device_flags_reappearance_and_volatile_signal(self) -> None:
        findings = evaluate_device(
            address="C1:44:09:33:71:B8",
            address_type="random",
            name=None,
            manufacturer_id=None,
            rssi_history=[-90, -55, -87, -50, -82, -48],
            seen_count=8,
            reappear_count=3,
            stale_seconds=0,
        )

        codes = {finding.code for finding in findings}
        severities = {finding.severity for finding in findings}
        self.assertIn("randomized-address", codes)
        self.assertIn("no-friendly-name", codes)
        self.assertIn("volatile-signal", codes)
        self.assertIn("repeated-reappearance", codes)
        self.assertIn(Severity.MEDIUM, severities)


if __name__ == "__main__":
    unittest.main()
