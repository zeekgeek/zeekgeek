"""Native macOS menu-bar app for MacBook Battery Diagnostic.

Requires PyObjC (Cocoa + WebKit), which only installs on macOS:
    pip install -e ".[menubar]"
    mac-battery-menubar

Unlike a plain rumps app, this shows the actual graphical dashboard —
the same charge bar, "what's going on" card, stats, and charts as
`mac-battery`'s web dashboard — in a native popover anchored to the
menu-bar icon, via an embedded WKWebView. A left click opens/closes the
popover; a right click gives a small Quit / Open in Browser menu.

This module talks directly to AppKit/WebKit rather than a wrapper
library because there isn't a clean way to attach a custom NSPopover to
a status item through rumps: rumps always wires the status item straight
to a plain-text NSMenu (see its `NSApp.initializeStatusBar`), which is
why the earlier text-only version couldn't show real graphics.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import threading
import webbrowser

try:
    from AppKit import (
        NSApplication,
        NSApplicationActivationPolicyAccessory,
        NSMenu,
        NSMenuItem,
        NSPopover,
        NSStatusBar,
        NSVariableStatusItemLength,
        NSViewController,
    )
    from Foundation import NSMakeRect, NSMakeSize, NSObject, NSTimer, NSURL, NSURLRequest
    from WebKit import WKWebView, WKWebViewConfiguration
except ImportError as exc:  # pragma: no cover - exercised only off macOS
    raise SystemExit(
        "The menu-bar app requires PyObjC's Cocoa and WebKit bindings, which only\n"
        "install on macOS. Run: pip install -e '.[menubar]'"
    ) from exc

try:
    from AppKit import NSEventTypeRightMouseUp as _RIGHT_MOUSE_UP
except ImportError:  # older PyObjC naming
    from AppKit import NSRightMouseUp as _RIGHT_MOUSE_UP

from .__main__ import pick_available_port
from .metrics import ChargeRateTracker, build_report
from .reader import open_reader
from .state import BatteryState
from .web import create_app

LOGGER = logging.getLogger(__name__)

_NS_MIN_Y_EDGE = 1  # NSRectEdge.minY: show the popover below the status item
_POPOVER_TRANSIENT = 1  # NSPopoverBehavior.transient: closes on outside click


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


class AppDelegate(NSObject):
    """NSApplication delegate: owns the status item, popover, and refresh timer.

    Configuration (reader/state/dashboard_url/etc.) is set as plain
    Python attributes on the instance right after `alloc().init()`,
    before `applicationDidFinishLaunching_` fires — simpler than wiring
    a custom Objective-C initializer selector for a handful of values.
    """

    def applicationDidFinishLaunching_(self, notification) -> None:
        status_bar = NSStatusBar.systemStatusBar()
        self.status_item = status_bar.statusItemWithLength_(NSVariableStatusItemLength)
        button = self.status_item.button()
        button.setTitle_("Battery —")
        button.setTarget_(self)
        button.setAction_("statusItemClicked:")

        self.popover = NSPopover.alloc().init()
        self.popover.setContentSize_(NSMakeSize(380, 660))
        self.popover.setBehavior_(_POPOVER_TRANSIENT)

        webview_config = WKWebViewConfiguration.alloc().init()
        self.webview = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, 380, 660), webview_config
        )
        self.webview.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(self.dashboard_url)))

        view_controller = NSViewController.alloc().init()
        view_controller.setView_(self.webview)
        self.popover.setContentViewController_(view_controller)

        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            self.refresh_interval, self, "refreshTitle:", None, True
        )

    def statusItemClicked_(self, sender) -> None:
        event = NSApplication.sharedApplication().currentEvent()
        if event is not None and event.type() == _RIGHT_MOUSE_UP:
            self._showContextMenu()
            return
        if self.popover.isShown():
            self.popover.performClose_(sender)
        else:
            self.popover.showRelativeToRect_ofView_preferredEdge_(
                sender.bounds(), sender, _NS_MIN_Y_EDGE
            )

    def _showContextMenu(self) -> None:
        menu = NSMenu.alloc().init()

        open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open in Browser", "openInBrowser:", ""
        )
        open_item.setTarget_(self)
        menu.addItem_(open_item)

        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "terminate:", "")
        quit_item.setTarget_(NSApplication.sharedApplication())
        menu.addItem_(quit_item)

        self.status_item.setMenu_(menu)
        self.status_item.button().performClick_(None)
        self.status_item.setMenu_(None)  # detach so the next left click hits statusItemClicked_ again

    def openInBrowser_(self, sender) -> None:
        webbrowser.open(self.dashboard_url)

    def refreshTitle_(self, timer) -> None:
        report = self.state.latest
        if report is None:
            return
        e, c = report["electrical"], report["charging"]
        if e["amperage_ma"] > 50:
            arrow = "↑"
        elif e["amperage_ma"] < -50:
            arrow = "↓"
        else:
            arrow = "•"
        pct = c["charge_percent"]
        pct_label = f"{pct:.0f}%" if pct is not None else "—"
        self.status_item.button().setTitle_(f"{arrow} {abs(e['watts']):.1f}W {pct_label}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Native macOS menu-bar battery power monitor. The status item shows live "
            "wattage + charge %; click it for the full graphical dashboard in a popover."
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

    reader = open_reader(force_demo=args.demo)
    state = BatteryState()
    rate = ChargeRateTracker()
    dashboard_port = pick_available_port(args.host, args.port)
    dashboard_url = f"http://localhost:{dashboard_port}/"
    print(f"Battery dashboard (also shown in the menu-bar popover): {dashboard_url}")

    threading.Thread(
        target=lambda: asyncio.run(
            _serve_dashboard(
                reader,
                state,
                rate,
                interval=args.interval,
                target=args.target,
                host=args.host,
                port=dashboard_port,
            )
        ),
        daemon=True,
        name="battery-dashboard-server",
    ).start()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # no Dock icon

    delegate = AppDelegate.alloc().init()
    delegate.state = state
    delegate.dashboard_url = dashboard_url
    delegate.refresh_interval = args.interval
    app.setDelegate_(delegate)

    app.run()


if __name__ == "__main__":
    main()
