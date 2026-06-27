"""Command-line entry point for the Bluetooth radar."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from contextlib import suppress

import uvicorn

from .scanner import BleakScannerBackend, DemoScannerBackend
from .state import RadarState
from .web import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bluetooth proximity radar")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=8765, help="Dashboard port")
    parser.add_argument("--stale-after", type=float, default=20.0, help="Seconds before a missing device is marked left")
    parser.add_argument("--demo", action="store_true", help="Use simulated Bluetooth devices instead of live hardware")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    asyncio.run(run(args))


async def run(args: argparse.Namespace) -> None:
    state = RadarState(stale_after=args.stale_after)
    app = create_app(state)
    scanner = DemoScannerBackend(state) if args.demo else BleakScannerBackend(state)
    scanner_task = asyncio.create_task(scanner.run(), name="bluetooth-scanner")

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level=args.log_level)
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(), name="dashboard-server")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    print(f"Bluetooth radar dashboard: http://{args.host}:{args.port}")
    if args.demo:
        print("Running in demo mode with simulated devices.")
    else:
        print("Running live Bluetooth scan. Linux may require bluetoothd, adapter power, and scan permissions.")

    done, pending = await asyncio.wait(
        {scanner_task, server_task, asyncio.create_task(stop_event.wait())},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in done:
        if task is not server_task and task is not scanner_task:
            continue
        exception = task.exception()
        if exception is not None:
            raise exception

    server.should_exit = True
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


if __name__ == "__main__":
    main()
