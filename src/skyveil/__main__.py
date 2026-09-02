"""Command-line entry point for SkyVeil."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
from contextlib import suppress

import uvicorn

from .scanner import DEFAULT_CENTER, DEFAULT_RADIUS_NM, AdsbLolBackend, DemoScannerBackend
from .state import DETECTION_SCORE_THRESHOLD, SkyState
from .web import create_app

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SkyVeil: public-ADS-B flight anomaly radar")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=8795, help="Dashboard port")
    parser.add_argument("--demo", action="store_true", help="Simulate traffic instead of polling live ADS-B")
    parser.add_argument("--poll-interval", type=float, default=20.0, help="Seconds between live ADS-B polls")
    parser.add_argument(
        "--stale-after",
        type=float,
        default=None,
        help="Seconds before a missing flight is marked as left coverage (default: 90 live / 6 demo)",
    )
    parser.add_argument(
        "--detection-threshold",
        type=float,
        default=DETECTION_SCORE_THRESHOLD,
        help="Anomaly score (0-100) at which a flight joins the detections feed",
    )
    parser.add_argument(
        "--center",
        default=None,
        help="'lat,lon' to center the regional watch on (default: continental US center)",
    )
    parser.add_argument(
        "--radius-nm",
        type=float,
        default=DEFAULT_RADIUS_NM,
        help="Regional watch radius in nautical miles (adsb.lol caps this around 250nm)",
    )
    parser.add_argument(
        "--no-auto-demo-fallback",
        action="store_true",
        help="Exit if the live ADS-B feed fails instead of switching to demo mode",
    )
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def parse_center(raw: str | None) -> tuple[float, float]:
    if not raw:
        return DEFAULT_CENTER
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
    stale_after = args.stale_after if args.stale_after is not None else (6.0 if args.demo else 90.0)
    state = SkyState(stale_after=stale_after, detection_threshold=args.detection_threshold)
    app = create_app(state)
    scanner_task = asyncio.create_task(
        _run_scanner(
            state=state,
            force_demo=args.demo,
            auto_demo_fallback=not args.no_auto_demo_fallback,
            poll_interval=args.poll_interval,
            center=parse_center(args.center),
            radius_nm=args.radius_nm,
        ),
        name="skyveil-scanner",
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

    print(f"SkyVeil dashboard: http://{args.host}:{chosen_port}")
    if args.demo:
        print("Running in demo mode: one simulated flight per anomaly category.")
    else:
        lat, lon = parse_center(args.center)
        print(
            f"Polling live ADS-B from adsb.lol: {args.radius_nm:.0f}nm around ({lat:.2f},{lon:.2f}) "
            "plus global emergency/PIA/LADD/military feeds."
        )

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
    state: SkyState,
    force_demo: bool,
    auto_demo_fallback: bool,
    poll_interval: float,
    center: tuple[float, float],
    radius_nm: float,
) -> None:
    if force_demo:
        await DemoScannerBackend(state).run()
        return

    try:
        await AdsbLolBackend(state, interval=poll_interval, center=center, radius_nm=radius_nm).run()
    except Exception as exc:
        message = f"Live ADS-B feed unavailable ({type(exc).__name__}: {exc}). Switching to demo scanner."
        LOGGER.warning(message)
        await state.add_system_event("scanner-fallback", message)
        if not auto_demo_fallback:
            raise
        print(message)
        await DemoScannerBackend(state).run()


if __name__ == "__main__":
    main()
