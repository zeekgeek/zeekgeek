"""Tests for the slow tone sweep dashboard."""

from __future__ import annotations

import socket
import unittest

from tone_sweep.__main__ import pick_available_port
from tone_sweep.sweep import SweepConfig, sweep_frequency
from tone_sweep.web import DASHBOARD_HTML, create_app


class SweepTests(unittest.TestCase):
    def test_frequency_sweeps_up_and_back_down(self) -> None:
        config = SweepConfig(sweep_seconds=90)
        self.assertEqual(sweep_frequency(0, config), 47)
        self.assertEqual(sweep_frequency(45, config), 56)
        self.assertEqual(sweep_frequency(90, config), 65)
        self.assertEqual(sweep_frequency(135, config), 56)
        self.assertEqual(sweep_frequency(180, config), 47)

    def test_negative_elapsed_time_starts_at_lower_bound(self) -> None:
        self.assertEqual(sweep_frequency(-20), 47)

    def test_config_rejects_unsafe_or_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            SweepConfig(low_hz=0)
        with self.assertRaises(ValueError):
            SweepConfig(low_hz=65, high_hz=47)
        with self.assertRaises(ValueError):
            SweepConfig(sweep_seconds=5)
        with self.assertRaises(ValueError):
            SweepConfig(max_gain=0.5)


class AppTests(unittest.TestCase):
    def test_routes_exist(self) -> None:
        app = create_app()
        paths = {getattr(route, "path", None) for route in app.routes}
        self.assertIn("/", paths)
        self.assertIn("/api/config", paths)

    def test_dashboard_contains_audio_controls_and_safety_copy(self) -> None:
        for needle in (
            "AudioContext",
            'value="0"',
            "47 to 65 Hz",
            "Keep its hardware volume low",
            "keep the speaker off your skin",
            "not medical use",
            "JBL Flip 5 note",
        ):
            self.assertIn(needle, DASHBOARD_HTML)

    def test_pick_available_port_skips_busy_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            occupied = sock.getsockname()[1]
            chosen = pick_available_port("127.0.0.1", occupied, max_tries=4)
        self.assertGreaterEqual(chosen, occupied + 1)


if __name__ == "__main__":
    unittest.main()
