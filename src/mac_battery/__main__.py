"""Command-line entry point for MacBook battery diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
import sys
import time
from contextlib import suppress

import uvicorn

from .display import print_live, render_snapshot
from .metrics import ChargeRateTracker, build_report
from .reader import open_reader
from .state import BatteryState
from .web import create_app

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Realtime MacBook battery diagnostic: charging voltage, watts, amperage, "
            "health, cycles, and ETA to 80% / full."
        )
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print a single snapshot and exit (no live refresh / dashboard)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between samples (default: 1.0)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Dashboard bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8780,
        help="Dashboard port (default: 8780)",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Terminal-only live monitor (skip the web dashboard)",
    )
    parser.add_argument(
        "--no-terminal",
        action="store_true",
        help="Dashboard only (skip clearing/redrawing the terminal)",
    )
    parser.add_argument("--demo", action="store_true", help="Simulate a 2018 MBP charge session")
    parser.add_argument(
        "--no-auto-demo-fallback",
        action="store_true",
        help="Exit if live AppleSmartBattery / ioreg is unavailable",
    )
    parser.add_argument(
        "--target",
        type=float,
        default=80.0,
        help="Optimized charge target percent for ETA (default: 80)",
    )
    parser.add_argument("--log-level", default="warning", choices=["debug", "info", "warning", "error"])
    return parser


def pick_available_port(host: str, preferred: int, max_tries: int = 30) -> int:
    port = preferred
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                port += 1
                continue
            return port
    raise RuntimeError(f"No free port found near {preferred}")


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    try:
        reader = open_reader(
            force_demo=args.demo,
            auto_demo_fallback=not args.no_auto_demo_fallback,
        )
    except Exception as exc:
        print(f"Unable to open battery reader: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.once:
        sample = reader.read()
        rate = ChargeRateTracker()
        rate.add(sample.amperage_ma)
        report = build_report(sample, rate, target_optimized=args.target)
        print(render_snapshot(report))
        if report["source"] == "demo" and not args.demo:
            print("\n(Note: running on demo data — live ioreg unavailable on this host.)")
        return

    asyncio.run(run_live(args, reader))


async def run_live(args: argparse.Namespace, reader) -> None:
    state = BatteryState()
    rate = ChargeRateTracker()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    sampler = asyncio.create_task(
        _sample_loop(reader, state, rate, args.interval, args.target, stop_event),
        name="battery-sampler",
    )

    server_task = None
    if not args.no_web:
        chosen_port = pick_available_port(args.host, args.port)
        if chosen_port != args.port:
            print(f"Port {args.port} is busy; using port {chosen_port} instead.")
        app = create_app(state)
        config = uvicorn.Config(app, host=args.host, port=chosen_port, log_level=args.log_level)
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve(), name="battery-dashboard")
        print(f"Battery dashboard: http://{args.host}:{chosen_port}")

    if args.demo or getattr(reader, "name", "") == "DemoBatteryReader":
        print("Running in demo mode (simulated 2018 MacBook Pro charge session).")
    else:
        print("Reading live AppleSmartBattery via ioreg.")

    terminal_task = None
    if not args.no_terminal:
        terminal_task = asyncio.create_task(
            _terminal_loop(state, stop_event, args.interval),
            name="terminal-ui",
        )
    else:
        print("Terminal UI disabled; use the dashboard URL above.")

    await stop_event.wait()
    sampler.cancel()
    if terminal_task:
        terminal_task.cancel()
    if server_task:
        server_task.cancel()
    with suppress(asyncio.CancelledError):
        await sampler
        if terminal_task:
            await terminal_task
        if server_task:
            await server_task


async def _sample_loop(reader, state, rate, interval, target, stop_event) -> None:
    while not stop_event.is_set():
        try:
            sample = await asyncio.to_thread(reader.read)
            rate.add(sample.amperage_ma)
            report = build_report(sample, rate, target_optimized=target)
            state.update(report)
        except Exception:
            LOGGER.exception("Failed to sample battery")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.2, interval))
        except asyncio.TimeoutError:
            continue


async def _terminal_loop(state: BatteryState, stop_event: asyncio.Event, interval: float) -> None:
    # Wait briefly for first sample
    deadline = time.monotonic() + 5
    while state.latest is None and time.monotonic() < deadline and not stop_event.is_set():
        await asyncio.sleep(0.05)
    while not stop_event.is_set():
        if state.latest:
            print_live(state.latest, clear=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.2, interval))
        except asyncio.TimeoutError:
            continue


if __name__ == "__main__":
    main()
