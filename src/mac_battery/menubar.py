"""Native macOS menu-bar status item for MacBook Battery Diagnostic.

Requires `rumps` (PyObjC-based), which only works on macOS:
    pip install -e ".[menubar]"
    mac-battery-menubar

The status item itself is text-only (that's all a native NSStatusItem
title supports), but the app also runs the same graphical web dashboard
used by `mac-battery` in the background and adds an "Open Dashboard"
menu entry that opens it — one click for the full AlDente-style charts
and bars, no separate terminal command needed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import threading
import webbrowser

try:
    import rumps
except ImportError as exc:  # pragma: no cover - exercised only off macOS
    raise SystemExit(
        "The menu-bar app requires the 'rumps' package, which only installs on macOS.\n"
        "Run: pip install -e '.[menubar]'"
    ) from exc

from .__main__ import pick_available_port
from .metrics import ChargeRateTracker, build_report
from .reader import open_reader
from .state import BatteryState
from .web import create_app

LOGGER = logging.getLogger(__name__)


async def _serve_dashboard(
    reader,
    state: BatteryState,
    rate: ChargeRateTracker,
    *,
    interval: float,
    target: float,
    host: str,
    port: int,
) -> None:
    """Sample the battery and serve the graphical dashboard, forever."""
    import uvicorn

    async def sample_loop() -> None:
        while True:
            try:
                sample = await asyncio.to_thread(reader.read)
                rate.add(sample.amperage_ma)
                report = build_report(sample, rate, target_optimized=target)
                state.update(report)
            except Exception:
                LOGGER.exception("menu bar: failed to sample battery")
            await asyncio.sleep(max(0.2, interval))

    app = create_app(state)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    await asyncio.gather(sample_loop(), server.serve())


class BatteryMenuBarApp(rumps.App):
    """Menu-bar title shows live wattage + charge %; menu has the rest plus a dashboard link."""

    def __init__(
        self,
        *,
        interval: float = 2.0,
        target: float = 80.0,
        demo: bool = False,
        host: str = "127.0.0.1",
        port: int = 8780,
    ) -> None:
        super().__init__("MacBook Battery", title="Battery —")
        self.target = target
        self.host = host
        self.reader = open_reader(force_demo=demo)
        self.state = BatteryState()
        self.rate = ChargeRateTracker()
        self.dashboard_port = pick_available_port(host, port)

        self.item_dashboard = rumps.MenuItem("Open Dashboard…", callback=self.open_dashboard)
        self.item_power = rumps.MenuItem("Power: —")
        self.item_voltage = rumps.MenuItem("Voltage: —")
        self.item_amperage = rumps.MenuItem("Amperage: —")
        self.item_health = rumps.MenuItem("Health: —")
        self.item_cycles = rumps.MenuItem("Cycles: —")
        self.item_eta = rumps.MenuItem("ETA: —")
        self.item_source = rumps.MenuItem("Source: —")
        self.menu = [
            self.item_dashboard,
            None,
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

        dashboard_url = f"http://{self.host}:{self.dashboard_port}/"
        print(f"Battery dashboard (opens from the menu bar too): {dashboard_url}")

        threading.Thread(
            target=lambda: asyncio.run(
                _serve_dashboard(
                    self.reader,
                    self.state,
                    self.rate,
                    interval=interval,
                    target=target,
                    host=host,
                    port=self.dashboard_port,
                )
            ),
            daemon=True,
            name="battery-dashboard-server",
        ).start()

        self.timer = rumps.Timer(self.refresh, interval)
        self.timer.start()

    def open_dashboard(self, _sender: "rumps.MenuItem") -> None:
        webbrowser.open(f"http://{self.host}:{self.dashboard_port}/")

    def refresh(self, _sender: "rumps.Timer | None") -> None:
        report = self.state.latest
        if report is None:
            self.title = "Battery —"
            return

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
        description=(
            "Native macOS menu-bar battery power monitor (wattage + charge % in the bar), "
            "with a one-click link to the full graphical dashboard."
        )
    )
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between refreshes (default: 2.0)")
    parser.add_argument("--target", type=float, default=80.0, help="Optimized charge target percent (default: 80)")
    parser.add_argument("--demo", action="store_true", help="Simulate a 2018 MBP charge session")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8780, help="Dashboard port (default: 8780)")
    parser.add_argument("--log-level", default="warning", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    app = BatteryMenuBarApp(
        interval=args.interval,
        target=args.target,
        demo=args.demo,
        host=args.host,
        port=args.port,
    )
    app.run()


if __name__ == "__main__":
    main()
