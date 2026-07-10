import unittest

from wifi_radar.scanner import parse_iw_scan

SAMPLE = """
BSS a0:11:22:33:44:01(on wlan0)
	freq: 2437
	signal: -52.00 dBm
	SSID: HomeRouter
	last seen: 10 ms ago
BSS b4:aa:bb:cc:dd:03(on wlan0)
	freq: 5180
	signal: -70.00 dBm
	SSID: OfficeAP
BSS c8:de:ad:be:ef:04(on wlan0)
	freq: 2412
	signal: -80.00 dBm
	SSID:
"""


class ScannerParseTests(unittest.TestCase):
    def test_parses_bssid_signal_and_ssid(self) -> None:
        observations = parse_iw_scan(SAMPLE)
        self.assertEqual(len(observations), 3)

        first = observations[0]
        self.assertEqual(first.bssid, "a0:11:22:33:44:01")
        self.assertEqual(first.rssi, -52)
        self.assertEqual(first.ssid, "HomeRouter")
        self.assertEqual(first.frequency_mhz, 2437)
        self.assertEqual(first.channel, 6)

        second = observations[1]
        self.assertEqual(second.frequency_mhz, 5180)
        self.assertEqual(second.channel, 36)

        hidden = observations[2]
        self.assertIsNone(hidden.ssid)

    def test_empty_output(self) -> None:
        self.assertEqual(parse_iw_scan(""), [])


if __name__ == "__main__":
    unittest.main()
