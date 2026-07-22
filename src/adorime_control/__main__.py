"""Command-line entry point for the AdoRime Bluetooth control app."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
from contextlib import suppress

import uvicorn

from .ble_stack import compact_error_for_api, live_scan_blocked_message, prepare_ble_runtime, startup_scan_hints
from .scanner import BleakScannerBackend, DemoScannerBackend
from .state import RadarState
from .web import create_app

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AdoRime Bluetooth control app")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=8785, help="Dashboard port")
    parser.add_argument("--stale-after", type=float, default=18.0, help="Seconds before a missing device is marked left")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use simulated Bluetooth devices (disables live scan)",
    )
    parser.add_argument(
        "--allow-demo-fallback",
        action="store_true",
        help="If live scan fails, switch to simulated devices (default is live-only, no fallback)",
    )
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def resolve_scan_mode_flags(args: argparse.Namespace) -> tuple[bool, bool]:
    """Return (force_demo, allow_demo_fallback). Live hardware is the default."""
    return bool(args.demo), bool(args.allow_demo_fallback)


def main() -> None:
    args = build_parser().parse_args()
    prepare_ble_runtime()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    force_demo, allow_demo_fallback = resolve_scan_mode_flags(args)
    for hint in startup_scan_hints(demo=force_demo):
        print(f"WARNING: {hint}")
    asyncio.run(run(args, force_demo=force_demo, allow_demo_fallback=allow_demo_fallback))


async def run(args: argparse.Namespace, *, force_demo: bool, allow_demo_fallback: bool) -> None:
    state = RadarState(stale_after=args.stale_after)
    app = create_app(state)
    scanner_task = asyncio.create_task(
        _run_scanner(
            state=state,
            force_demo=force_demo,
            allow_demo_fallback=allow_demo_fallback,
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
    if force_demo:
        print("Running in demo mode with simulated AdoRime devices.")
    elif allow_demo_fallback:
        print("Running live Bluetooth scan; simulated fallback is enabled if live scan fails.")
    else:
        print("Running live Bluetooth scan only (real advertisements; no simulated fallback).")

    done, pending = await asyncio.wait(
        {scanner_task, server_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    failure: Exception | None = None
    for task in done:
        if task is stop_task:
            continue
        if task is scanner_task:
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


async def _start_demo_scanner(state: RadarState, *, reason: str) -> None:
    message = (
        f"Live Bluetooth unavailable ({reason}). "
        "Switching to simulated devices because --allow-demo-fallback is set."
    )
    LOGGER.warning(message)
    await state.add_system_event("scanner-fallback", message)
    print(message)
    await DemoScannerBackend(state).run()


async def _park_live_error(state: RadarState, message: str) -> None:
    await state.set_scan_status(mode="live-error", error=message)
    await state.add_system_event("scanner-error", message)
    print(message)
    while True:
        await asyncio.sleep(60)


async def _run_scanner(*, state: RadarState, force_demo: bool, allow_demo_fallback: bool) -> None:
    if force_demo:
        await DemoScannerBackend(state).run()
        return

    blocked = live_scan_blocked_message()
    if blocked:
        if allow_demo_fallback:
            await _start_demo_scanner(state, reason=blocked)
            return
        await _park_live_error(state, blocked)
        return

    try:
        await BleakScannerBackend(state).run()
    except Exception as exc:
        strict_message = compact_error_for_api(exc)
        LOGGER.warning("Live scanner unavailable (%s)", strict_message)
        if allow_demo_fallback:
            await _start_demo_scanner(state, reason=strict_message)
            return
        await _park_live_error(
            state,
            f"Live scanner unavailable ({strict_message}). Dashboard stays live-only with no simulated data.",
        )


if __name__ == "__main__":
    main()
