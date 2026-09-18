"""Native macOS menu-bar status item for MacBook Battery Diagnostic.

Requires `rumps` (PyOjbC-based), which only works on macOS:
    pip install -e ".[menubar]"
    mac-battery-menubar
"""

from __future__ import annotations

import argparse
import logging

try:
    import rumps
except ImportError as exc:  # pragma: no cover - exercised only off macOS
    raise SystemExit(
        "The menu-bar app requires the 'rumps' package, which only installs on macOS.\n"
        "Run: pip install -e '.[menubar]'"
    ) from exc

from .metrics import ChargeRateTracker, build_report
from .reader import open_reader

LOGGER = logging.getLogger(__name__)


class BatteryMenuBarApp(rumps.App):
    """Menu-bar title shows live wattage + charge %; dropdown has the rest."""

    def __init__(self, *, interval: float = 2.0, target: float = 80.0, demo: bool = False) -> None:
        super().__init__("MacBook Battery", title="Battery —")
        self.target = target
        self.reader = open_reader(force_demo=demo)
        self.rate = ChargeRateTracker()

        self.item_power = rumps.MenuItem("Power: —")
        self.item_voltage = rumps.MenuItem("Voltage: —")
        self.item_amperage = rumps.MenuItem("Amperage: —")
        self.item_health = rumps.MenuItem("Health: —")
        self.item_cycles = rumps.MenuItem("Cycles: —")
        self.item_eta = rumps.MenuItem("ETA: —")
        self.item_source = rumps.MenuItem("Source: —")
        self.menu = [
            self.item_power,
            self.item_voltage,
            self.item_amperage,
            None,
            self.item_health,
            self.item_cycles,
            self.item_eta,
            None,
            self.item_source,
        ]

        self.timer = rumps.Timer(self.refresh, interval)
        self.timer.start()
        self.refresh(None)

    def refresh(self, _sender: "rumps.Timer | None") -> None:
        try:
            sample = self.reader.read()
        except Exception as exc:  # keep the app alive across a transient ioreg failure
            LOGGER.warning("battery read failed: %s", exc)
            self.title = "⚠ battery"
            return

        self.rate.add(sample.amperage_ma)
        report = build_report(sample, self.rate, target_optimized=self.target)
        e, c, h = report["electrical"], report["charging"], report["health"]

        if e["amperage_ma"] > 50:
            arrow = "↑"
        elif e["amperage_ma"] < -50:
            arrow = "↓"
        else:
            arrow = "•"
        pct = c["charge_percent"]
        pct_label = f"{pct:.0f}%" if pct is not None else "—"
        self.title = f"{arrow} {abs(e['watts']):.1f}W {pct_label}"

        self.item_power.title = f"Power: {e['watts']:.2f} W"
        self.item_voltage.title = f"Voltage: {e['voltage_v']:.3f} V"
        self.item_amperage.title = f"Amperage: {e['amperage_a']:.3f} A"
        health = h["health_percent"]
        self.item_health.title = (
            f"Health: {health:.0f}% ({h['health_band']})" if health is not None else "Health: —"
        )
        self.item_cycles.title = f"Cycles: {h['cycle_count']} / {h['design_cycle_count']}"
        self.item_eta.title = (
            f"To {c['optimized_target_percent']:g}%: {c['eta_to_80_label']} "
            f"· Full: {c['eta_to_full_label']}"
        )
        self.item_source.title = f"Source: {report['source']}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Native macOS menu-bar battery power monitor (wattage + charge % in the bar)."
    )
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between refreshes (default: 2.0)")
    parser.add_argument("--target", type=float, default=80.0, help="Optimized charge target percent (default: 80)")
    parser.add_argument("--demo", action="store_true", help="Simulate a 2018 MBP charge session")
    parser.add_argument("--log-level", default="warning", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    app = BatteryMenuBarApp(interval=args.interval, target=args.target, demo=args.demo)
    app.run()


if __name__ == "__main__":
    main()
