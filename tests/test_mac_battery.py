"""Unit tests for mac_battery metrics and demo reader."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from mac_battery.metrics import (
    BatterySample,
    ChargeRateTracker,
    build_report,
    format_duration,
    health_band,
)
from mac_battery.reader import DemoBatteryReader, _as_signed_ma


def _sample(**overrides) -> BatterySample:
    base = dict(
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        voltage_mv=12150,
        amperage_ma=3000,
        design_capacity_mah=7336,
        max_capacity_mah=6250,
        current_capacity_mah=3125,  # 50%
        cycle_count=487,
        design_cycle_count=1000,
        temperature_cC=3120,
        is_charging=True,
        external_connected=True,
        fully_charged=False,
        apple_time_remaining_min=60,
        serial="TEST",
        device_name="bq20z451",
        manufacturer="SMP",
        source="test",
    )
    base.update(overrides)
    return BatterySample(**base)


class MetricsTests(unittest.TestCase):
    def test_watts_and_health(self) -> None:
        sample = _sample()
        self.assertAlmostEqual(sample.voltage_v, 12.15)
        self.assertAlmostEqual(sample.amperage_a, 3.0)
        self.assertAlmostEqual(sample.watts, 36.45, places=2)
        self.assertAlmostEqual(sample.health_percent or 0, 100.0 * 6250 / 7336, places=1)
        self.assertAlmostEqual(sample.charge_percent or 0, 50.0, places=1)

    def test_percent_mode_capacity(self) -> None:
        sample = _sample(max_capacity_mah=85, current_capacity_mah=50, design_capacity_mah=7336)
        self.assertEqual(sample.health_percent, 85.0)
        self.assertEqual(sample.charge_percent, 50.0)

    def test_eta_to_80_and_full(self) -> None:
        sample = _sample(current_capacity_mah=3125, amperage_ma=3000)  # 50% of 6250
        rate = ChargeRateTracker()
        for _ in range(5):
            rate.add(3000)
        report = build_report(sample, rate, target_optimized=80.0)
        # Remaining to 80%: 0.3 * 6250 = 1875 mAh / 3000 mA = 0.625 h = 37.5 min
        self.assertAlmostEqual(report["charging"]["eta_to_80_min"], 37.5, places=1)
        # Remaining to full: 3125 / 3000 * 60 ≈ 62.5 min
        self.assertAlmostEqual(report["charging"]["eta_to_full_min"], 62.5, places=1)
        self.assertIn("min", report["charging"]["eta_to_80_label"])

    def test_already_at_80(self) -> None:
        sample = _sample(current_capacity_mah=5200)  # >80% of 6250
        rate = ChargeRateTracker()
        rate.add(2000)
        report = build_report(sample, rate)
        self.assertIsNone(report["charging"]["eta_to_80_min"])
        self.assertEqual(report["charging"]["eta_to_80_label"], "already ≥ 80%")

    def test_format_duration_and_bands(self) -> None:
        self.assertEqual(format_duration(None), "—")
        self.assertEqual(format_duration(0), "reached")
        self.assertEqual(format_duration(75), "1 h 15 min")
        self.assertEqual(health_band(92), "Excellent")
        self.assertEqual(health_band(75), "Fair")

    def test_signed_amperage_wrap(self) -> None:
        self.assertEqual(_as_signed_ma(1000), 1000)
        self.assertEqual(_as_signed_ma(2**32 - 500), -500)


class DemoReaderTests(unittest.TestCase):
    def test_demo_produces_charging_sample(self) -> None:
        reader = DemoBatteryReader(start_percent=40.0, charge_ma=3000)
        sample = reader.read()
        self.assertTrue(sample.external_connected)
        self.assertGreater(sample.voltage_mv, 10000)
        self.assertEqual(sample.source, "demo")
        self.assertGreater(sample.design_capacity_mah, 0)
        report = build_report(sample, ChargeRateTracker())
        self.assertIn("electrical", report)
        self.assertIn("health", report)


class DisplayImportTests(unittest.TestCase):
    def test_render_contains_targets(self) -> None:
        from mac_battery.display import render_snapshot

        sample = _sample()
        rate = ChargeRateTracker()
        rate.add(sample.amperage_ma)
        text = render_snapshot(build_report(sample, rate))
        self.assertIn("Voltage", text)
        self.assertIn("→ 80%", text)
        self.assertIn("→ Full", text)
        self.assertIn("Cycles", text)


if __name__ == "__main__":
    unittest.main()
