"""Command-line entry point for the private-jet movement radar."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
from contextlib import suppress

import uvicorn

from .anomaly import DEFAULT_SIGMA, DEFAULT_TRIGGER_THRESHOLD
from .scanner import AdsbLolBackend, DemoScannerBackend
from .state import RadarState
from .web import create_app

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Private jet movement radar with strange-event alarm")
    parser.add_argument("--host", default="0.0.0.0", help="Dashboard bind address (0.0.0.0 for browser access)")
    parser.add_argument("--port", type=int, default=8790, help="Dashboard port")
    parser.add_argument("--demo", action="store_true", help="Simulate jet traffic instead of polling live ADS-B")
    parser.add_argument("--poll-interval", type=float, default=60.0, help="Seconds between live ADS-B polls")
    parser.add_argument(
        "--stale-after",
        type=float,
        default=None,
        help="Seconds before a missing jet is marked as left coverage (default: 180 live / 6 demo)",
    )
    parser.add_argument("--sigma", type=float, default=DEFAULT_SIGMA, help="Z-score above baseline for surge triggers")
    parser.add_argument(
        "--trigger-threshold",
        type=int,
        default=DEFAULT_TRIGGER_THRESHOLD,
        help="Movement triggers in the recent window needed to sound the strange-event alarm",
    )
    parser.add_argument(
        "--baseline-samples",
        type=int,
        default=None,
        help="Poll cycles of history required before anomaly scoring (default: 10 live / 8 demo)",
    )
    parser.add_argument("--center", default=None, help="Optional 'lat,lon' to watch a region instead of the whole feed")
    parser.add_argument("--radius-nm", type=float, default=250.0, help="Region radius in nautical miles when --center is set")
    parser.add_argument(
        "--allow-demo-fallback",
        action="store_true",
        help="If live ADS-B fails, switch to simulated demo data (off by default — live only)",
    )
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def parse_center(raw: str | None) -> tuple[float, float] | None:
    if not raw:
        return None
    parts = raw.split(",")
    if len(parts) != 2:
        raise SystemExit("--center must be 'lat,lon', e.g. --center 38.9,-77.0")
    try:
        return float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise SystemExit(f"--center must be numeric 'lat,lon': {exc}") from exc


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    asyncio.run(run(args))


async def run(args: argparse.Namespace) -> None:
    cycle_seconds = 2.0 if args.demo else args.poll_interval
    stale_after = args.stale_after if args.stale_after is not None else (6.0 if args.demo else 180.0)
    baseline_samples = args.baseline_samples if args.baseline_samples is not None else (8 if args.demo else 10)
    # Demo packs many anomaly types into a short window; a slightly lower threshold
    # still requires correlated triggers before the strange-event alarm fires.
    trigger_threshold = args.trigger_threshold if not args.demo or args.trigger_threshold != DEFAULT_TRIGGER_THRESHOLD else 3

    state = RadarState(
        stale_after=stale_after,
        sigma=args.sigma,
        trigger_threshold=trigger_threshold,
        min_baseline_samples=baseline_samples,
        cycle_seconds=cycle_seconds,
    )
    app = create_app(state)
    scanner_task = asyncio.create_task(
        _run_scanner_loop(
            state=state,
            force_demo=args.demo,
            auto_demo_fallback=args.allow_demo_fallback,
            poll_interval=args.poll_interval,
            center=parse_center(args.center),
            radius_nm=args.radius_nm,
        ),
        name="jet-scanner",
    )

    bind_host = args.host
    display_host = "127.0.0.1" if bind_host in {"0.0.0.0", "::"} else bind_host
    chosen_port = pick_available_port(bind_host, args.port)
    if chosen_port != args.port:
        message = f"Port {args.port} is busy; using port {chosen_port} instead."
        print(message)
        await state.add_system_event("port-reassigned", message)

    config = uvicorn.Config(app, host=bind_host, port=chosen_port, log_level=args.log_level)
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(), name="dashboard-server")

    stop_event = asyncio.Event()
    stop_task = asyncio.create_task(stop_event.wait(), name="stop-wait")
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    print(f"Jet radar dashboard: http://{display_host}:{chosen_port}")
    if bind_host in {"0.0.0.0", "::"}:
        print(f"Listening on all interfaces (bound to {bind_host}:{chosen_port}).")
    if args.demo:
        print("Running in demo mode with simulated jet traffic.")
    else:
        print("Live-only mode: polling ADS-B from adsb.lol (no demo fallback).")

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
            if isinstance(exception, SystemExit):
                failure = RuntimeError(f"Dashboard failed to start on {bind_host}:{chosen_port}.")
            else:
                failure = exception

    server.should_exit = True
    scanner_task.cancel()
    remaining: list[asyncio.Task] = []
    for task in pending:
        if task is server_task:
            remaining.append(task)
            continue
        task.cancel()
        remaining.append(task)
    await asyncio.gather(scanner_task, *remaining, return_exceptions=True)
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


async def _run_scanner_loop(
    *,
    state: RadarState,
    force_demo: bool,
    auto_demo_fallback: bool,
    poll_interval: float,
    center: tuple[float, float] | None,
    radius_nm: float,
) -> None:
    """Keep the scanner running; restart after unexpected exits."""
    while True:
        try:
            await _run_scanner(
                state=state,
                force_demo=force_demo,
                auto_demo_fallback=auto_demo_fallback,
                poll_interval=poll_interval,
                center=center,
                radius_nm=radius_nm,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.exception("Scanner loop error: %s", exc)
            await state.add_system_event("scanner-restart", f"Scanner restarting after error: {exc}")
            await asyncio.sleep(5)


async def _run_scanner(
    *,
    state: RadarState,
    force_demo: bool,
    auto_demo_fallback: bool,
    poll_interval: float,
    center: tuple[float, float] | None,
    radius_nm: float,
) -> None:
    if force_demo:
        await state.set_scan_status(mode="demo", awaiting_first_poll=True)
        await DemoScannerBackend(state).run()
        return

    await state.set_scan_status(mode="live", awaiting_first_poll=True)
    try:
        await AdsbLolBackend(
            state,
            interval=poll_interval,
            center=center,
            radius_nm=radius_nm,
        ).run()
    except Exception as exc:
        message = f"Live ADS-B feed unavailable ({type(exc).__name__}: {exc}). Switching to demo scanner."
        LOGGER.warning(message)
        await state.add_system_event("scanner-fallback", message)
        if not auto_demo_fallback:
            raise
        print(message)
        await state.set_scan_status(mode="demo", awaiting_first_poll=True)
        await DemoScannerBackend(state).run()


if __name__ == "__main__":
    main()
