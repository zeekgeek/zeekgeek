"""Command-line entry point for the AdoRime Bluetooth control app."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
from contextlib import suppress

import uvicorn

from .scanner import BleakScannerBackend, DemoScannerBackend
from .state import RadarState
from .web import create_app

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AdoRime Bluetooth control app")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=8785, help="Dashboard port")
    parser.add_argument("--stale-after", type=float, default=18.0, help="Seconds before a missing device is marked left")
    parser.add_argument("--demo", action="store_true", help="Use simulated Bluetooth devices instead of live hardware")
    parser.add_argument(
        "--allow-demo-fallback",
        action="store_true",
        help="If live scan fails, switch to demo data instead of keeping an empty live session",
    )
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    asyncio.run(run(args))


async def run(args: argparse.Namespace) -> None:
    state = RadarState(stale_after=args.stale_after)
    app = create_app(state)
    scanner_task = asyncio.create_task(
        _run_scanner(
            state=state,
            force_demo=args.demo,
            allow_demo_fallback=args.allow_demo_fallback,
        ),
        name="adorime-scanner",
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

    print(f"AdoRime control dashboard: http://{args.host}:{chosen_port}")
    if args.demo:
        print("Running in demo mode with simulated AdoRime devices.")
    elif args.allow_demo_fallback:
        print("Running live Bluetooth scan; demo fallback is enabled if live scan fails.")
    else:
        print("Running live Bluetooth scan (Galaku/AdoRime GATT path). Dashboard stays up if hardware is missing.")

    done, pending = await asyncio.wait(
        {scanner_task, server_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    failure: Exception | None = None
    for task in done:
        if task is stop_task:
            continue
        if task is scanner_task:
            # Scanner ending is not fatal when it parks in live-error idle mode.
            exception = task.exception()
            if exception is not None and not isinstance(exception, asyncio.CancelledError):
                LOGGER.warning("Scanner task ended with error: %s", exception)
            continue
        exception = task.exception()
        if exception is not None:
            if task is server_task and isinstance(exception, SystemExit):
                failure = RuntimeError(f"Dashboard failed to start on {args.host}:{chosen_port}.")
            else:
                failure = exception

    server.should_exit = True
    with suppress(Exception):
        await state.connections.disconnect_all()
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


async def _run_scanner(*, state: RadarState, force_demo: bool, allow_demo_fallback: bool) -> None:
    if force_demo:
        await DemoScannerBackend(state).run()
        return

    try:
        await BleakScannerBackend(state).run()
    except Exception as exc:
        strict_message = f"Live scanner unavailable ({type(exc).__name__}: {exc})."
        LOGGER.warning(strict_message)
        if allow_demo_fallback:
            fallback_message = f"{strict_message} Switching to demo scanner because --allow-demo-fallback is set."
            await state.add_system_event("scanner-fallback", fallback_message)
            print(fallback_message)
            await DemoScannerBackend(state).run()
            return

        # Keep dashboard alive with live mode + error status (no simulated devices).
        await state.set_scan_status(mode="live-error", error=str(exc))
        await state.add_system_event(
            "scanner-error",
            f"{strict_message} Dashboard remains available; connect a Bluetooth adapter and restart to scan.",
        )
        print(f"{strict_message} Keeping dashboard up without simulated data.")
        while True:
            await asyncio.sleep(60)


if __name__ == "__main__":
    main()
