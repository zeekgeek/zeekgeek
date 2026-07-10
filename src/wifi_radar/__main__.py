"""Command-line entry point for the WiFi motion radar."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
from contextlib import suppress

import uvicorn

from .scanner import DemoScannerBackend, IwScannerBackend
from .state import RadarState
from .web import create_app

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WiFi motion radar")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=8770, help="Dashboard port")
    parser.add_argument("--interface", default=None, help="WiFi interface to scan (auto-detected if omitted)")
    parser.add_argument("--stale-after", type=float, default=20.0, help="Seconds before a missing device is marked left")
    parser.add_argument("--alarm-range", type=float, default=5.0, help="Alarm when a device is within this many metres")
    parser.add_argument("--scan-interval", type=float, default=3.0, help="Seconds between live WiFi scans")
    parser.add_argument("--demo", action="store_true", help="Use simulated WiFi devices instead of live hardware")
    parser.add_argument(
        "--no-auto-demo-fallback",
        action="store_true",
        help="Exit if the live scanner fails instead of switching to demo mode",
    )
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    asyncio.run(run(args))


async def run(args: argparse.Namespace) -> None:
    state = RadarState(stale_after=args.stale_after, alarm_range_m=args.alarm_range)
    app = create_app(state)
    scanner_task = asyncio.create_task(
        _run_scanner(
            state=state,
            force_demo=args.demo,
            auto_demo_fallback=not args.no_auto_demo_fallback,
            interface=args.interface,
            scan_interval=args.scan_interval,
        ),
        name="wifi-scanner",
    )

    chosen_port = pick_available_port(args.host, args.port)
    if chosen_port != args.port:
        message = f"Port {args.port} is busy; using port {chosen_port} instead."
        print(message)
        await state.add_system_event("port-reassigned", message)

    config = uvicorn.Config(app, host=args.host, port=chosen_port, log_level=args.log_level)
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(), name="dashboard-server")

    stop_event = asyncio.Event()
    stop_task = asyncio.create_task(stop_event.wait(), name="stop-wait")
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    print(f"WiFi radar dashboard: http://{args.host}:{chosen_port}")
    if args.demo:
        print("Running in demo mode with simulated devices.")
    else:
        print("Running live WiFi scan with automatic demo fallback if unavailable.")

    done, pending = await asyncio.wait(
        {scanner_task, server_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    failure: Exception | None = None
    for task in done:
        if task is stop_task:
            continue
        exception = task.exception()
        if exception is not None:
            if task is server_task and isinstance(exception, SystemExit):
                failure = RuntimeError(f"Dashboard failed to start on {args.host}:{chosen_port}.")
            else:
                failure = exception

    server.should_exit = True
    remaining: list[asyncio.Task] = []
    for task in pending:
        if task is server_task:
            remaining.append(task)
            continue
        task.cancel()
        remaining.append(task)
    await asyncio.gather(*remaining, return_exceptions=True)
    if failure is not None:
        raise failure


def pick_available_port(host: str, preferred_port: int, max_tries: int = 30) -> int:
    for offset in range(max_tries + 1):
        candidate = preferred_port + offset
        if _port_is_available(host, candidate):
            return candidate
    return preferred_port


def _port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


async def _run_scanner(
    *,
    state: RadarState,
    force_demo: bool,
    auto_demo_fallback: bool,
    interface: str | None,
    scan_interval: float,
) -> None:
    if force_demo:
        await DemoScannerBackend(state).run()
        return

    try:
        await IwScannerBackend(state, interface=interface, interval=scan_interval).run()
    except Exception as exc:
        message = f"Live scanner unavailable ({type(exc).__name__}: {exc}). Switching to demo scanner."
        LOGGER.warning(message)
        await state.add_system_event("scanner-fallback", message)
        if not auto_demo_fallback:
            raise
        print(message)
        await DemoScannerBackend(state).run()


if __name__ == "__main__":
    main()
