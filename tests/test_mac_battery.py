"""Unit tests for mac_battery metrics, sysfs, ingest, and demo reader."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from mac_battery.metrics import (
    BatterySample,
    ChargeRateTracker,
    build_report,
    format_duration,
    health_band,
)
from mac_battery.reader import (
    DemoBatteryReader,
    LinuxSysfsBatteryReader,
    RemoteIngestBuffer,
    WaitingForSensor,
    _as_signed_ma,
    open_reader,
    sample_from_ioreg_tree,
    sample_from_payload,
)


def _sample(**overrides) -> BatterySample:
    base = dict(
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        voltage_mv=12150,
        amperage_ma=3000,
        design_capacity_mah=7336,
        max_capacity_mah=6250,
        current_capacity_mah=3125,
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


def _write_sysfs_battery(root: Path) -> Path:
    bat = root / "BAT0"
    bat.mkdir(parents=True)
    values = {
        "type": "Battery\n",
        "status": "Charging\n",
        "voltage_now": "11724000\n",  # µV
        "current_now": "3138000\n",  # µA
        "charge_full_design": "7336000\n",  # µAh
        "charge_full": "6250000\n",
        "charge_now": "2625000\n",
        "cycle_count": "487\n",
        "temp": "314\n",  # 31.4°C in decidegrees
        "manufacturer": "SMP\n",
        "model_name": "bq20z451\n",
        "serial_number": "SYSFSDEMO\n",
    }
    for name, content in values.items():
        (bat / name).write_text(content, encoding="utf-8")
    return bat


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
        sample = _sample(current_capacity_mah=3125, amperage_ma=3000)
        rate = ChargeRateTracker()
        for _ in range(5):
            rate.add(3000)
        report = build_report(sample, rate, target_optimized=80.0)
        self.assertAlmostEqual(report["charging"]["eta_to_80_min"], 37.5, places=1)
        self.assertAlmostEqual(report["charging"]["eta_to_full_min"], 62.5, places=1)
        self.assertIn("min", report["charging"]["eta_to_80_label"])

    def test_already_at_80(self) -> None:
        sample = _sample(current_capacity_mah=5200)
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


class SysfsReaderTests(unittest.TestCase):
    def test_reads_fake_sysfs_battery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sysfs_battery(root)
            reader = LinuxSysfsBatteryReader(root=root)
            sample = reader.read()
        self.assertEqual(sample.voltage_mv, 11724)
        self.assertEqual(sample.amperage_ma, 3138)
        self.assertTrue(sample.is_charging)
        self.assertEqual(sample.design_capacity_mah, 7336)
        self.assertEqual(sample.max_capacity_mah, 6250)
        self.assertEqual(sample.current_capacity_mah, 2625)
        self.assertEqual(sample.cycle_count, 487)
        self.assertAlmostEqual(sample.temperature_c, 31.4, places=1)
        self.assertTrue(sample.source.startswith("sysfs:"))

    def test_open_reader_sysfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sysfs_battery(root)
            reader = open_reader(source="sysfs", sysfs_root=root, auto_demo_fallback=False)
            sample = reader.read()
            self.assertEqual(sample.manufacturer, "SMP")


class IngestTests(unittest.TestCase):
    def test_remote_buffer_push_and_read(self) -> None:
        buf = RemoteIngestBuffer(stale_after_s=30)
        with self.assertRaises(WaitingForSensor):
            buf.read()
        buf.push(_sample(source="collect:ioreg"))
        sample = buf.read()
        self.assertEqual(sample.source, "collect:ioreg")

    def test_sample_from_payload(self) -> None:
        sample = sample_from_payload(
            {
                "voltage_mv": 12000,
                "amperage_ma": 2000,
                "design_capacity_mah": 7000,
                "max_capacity_mah": 6000,
                "current_capacity_mah": 3000,
                "is_charging": True,
                "temperature_c": 30.5,
                "source": "collect:ioreg",
            }
        )
        self.assertEqual(sample.temperature_cC, 3050)
        self.assertAlmostEqual(sample.watts, 24.0, places=1)

    def test_sample_from_ioreg_tree(self) -> None:
        tree = {
            "Voltage": 12100,
            "InstantAmperage": 2500,
            "DesignCapacity": 7336,
            "AppleRawMaxCapacity": 6200,
            "AppleRawCurrentCapacity": 3100,
            "CycleCount": 100,
            "DesignCycleCount9C": 1000,
            "Temperature": 3000,
            "IsCharging": True,
            "ExternalConnected": True,
            "FullyCharged": False,
            "TimeRemaining": 40,
            "Manufacturer": "SMP",
        }
        sample = sample_from_ioreg_tree(tree, source="ssh:mac")
        self.assertEqual(sample.source, "ssh:mac")
        self.assertEqual(sample.amperage_ma, 2500)


class DemoReaderTests(unittest.TestCase):
    def test_demo_produces_charging_sample(self) -> None:
        reader = DemoBatteryReader(start_percent=40.0, charge_ma=3000)
        sample = reader.read()
        self.assertTrue(sample.external_connected)
        self.assertGreater(sample.voltage_mv, 10000)
        self.assertEqual(sample.source, "demo")
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
