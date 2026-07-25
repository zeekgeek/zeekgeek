"""Command-line entry point for the Bluetooth thrust controller."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
import sys
from contextlib import suppress

import uvicorn

from .cli import scan_main
from .controller import ToyController
from .deep_scan import run_deep_scan_worker
from .demo_scanner import DemoScannerBackend
from .scanner import BleakScannerBackend
from .state import ControllerState
from .web import create_app

LOGGER = logging.getLogger(__name__)
SCANNER_RETRY_SECONDS = 10.0
DEFAULT_LOCAL_HOST = "127.0.0.1"
DEFAULT_CURSOR_HOST = "0.0.0.0"


def default_dashboard_host() -> str:
    if os.environ.get("CURSOR_AGENT") == "1":
        return DEFAULT_CURSOR_HOST
    return DEFAULT_LOCAL_HOST


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bluetooth scanner and Adorime thruster controller (GUI dashboard or: scan ...)",
    )
    parser.add_argument(
        "--host",
        default=default_dashboard_host(),
        help="Dashboard host (defaults to 0.0.0.0 in Cursor so the Ports panel can forward it)",
    )
    parser.add_argument("--port", type=int, default=8800, help="Dashboard port")
    parser.add_argument("--stale-after", type=float, default=20.0, help="Seconds before a missing toy is marked left")
    parser.add_argument("--max-throttle", type=int, default=100, help="Safety cap for throttle levels (0-100)")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Simulate nearby devices when no Bluetooth adapter is available (UI testing only)",
    )
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        raise SystemExit(scan_main(sys.argv[2:]))

    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    asyncio.run(run_gui(args))


async def run_gui(args: argparse.Namespace) -> None:
    state = ControllerState(stale_after=args.stale_after)
    controller = ToyController(state=state, max_throttle=max(1, min(100, int(args.max_throttle))))
    app = create_app(state, controller)
    scanner_task = asyncio.create_task(_run_scanner_with_retry(state, demo=args.demo), name="toy-scanner")
    deep_scan_task = asyncio.create_task(run_deep_scan_worker(state), name="deep-scan-worker")

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

    local_url = f"http://127.0.0.1:{chosen_port}"
    bind_url = f"http://{args.host}:{chosen_port}"
    print(f"Bluetooth scanner + thruster dashboard: {local_url}")
    if args.host in {"0.0.0.0", "::"}:
        print(f"Listening on all interfaces: {bind_url}")
        if os.environ.get("CURSOR_AGENT") == "1":
            print(
                "Cursor browser: open the Ports panel, forward port "
                f"{chosen_port}, then click Open in Browser (or use Simple Browser on the forwarded URL)."
            )
    print("Running live BLE scan. Use Deep Scan for GATT services and classic Bluetooth discovery.")

    done, pending = await asyncio.wait(
        {server_task, stop_task},
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
    scanner_task.cancel()
    deep_scan_task.cancel()
    remaining: list[asyncio.Task] = [scanner_task, deep_scan_task]
    for task in pending:
        if task is server_task:
            remaining.append(task)
            continue
        task.cancel()
        remaining.append(task)
    await asyncio.gather(*remaining, return_exceptions=True)
    if failure is not None:
        raise failure


async def _run_scanner_with_retry(state: ControllerState, *, demo: bool = False) -> None:
    if demo:
        await DemoScannerBackend(state).run()
        return

    auto_demo = os.environ.get("CURSOR_AGENT") == "1"
    failures = 0

    while True:
        try:
            await state.set_scanner_active(True, error=None)
            await BleakScannerBackend(state).run()
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failures += 1
            if auto_demo and failures >= 1:
                message = (
                    f"No Bluetooth adapter ({type(exc).__name__}). "
                    "Switching to demo scanner with simulated nearby devices."
                )
                LOGGER.warning(message)
                await state.add_system_event("scanner-demo-fallback", message)
                await DemoScannerBackend(state).run()
                return

            message = (
                f"Live scanner unavailable ({type(exc).__name__}: {exc}). "
                f"Ensure Bluetooth is on and your user can access the adapter. "
                f"Retrying in {int(SCANNER_RETRY_SECONDS)}s."
            )
            LOGGER.warning(message)
            await state.set_scanner_active(False, error=str(exc))
            await state.add_system_event("scanner-error", message)
            await asyncio.sleep(SCANNER_RETRY_SECONDS)


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


if __name__ == "__main__":
    main()
