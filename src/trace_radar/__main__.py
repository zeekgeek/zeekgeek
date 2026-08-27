"""Command-line entry point for the visual 3D traceroute radar."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
import subprocess
import sys
import webbrowser
from contextlib import suppress

import uvicorn

from .speedtest import run_speed_test
from .state import RadarState
from .tracer import DemoTracerBackend, LiveTracerBackend
from .web import create_app

LOGGER = logging.getLogger(__name__)

DEFAULT_TARGETS = ["one.one.one.one", "google.com"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PingPlotter-style hop health radar with WHOIS, DNS, port scan, and speed tests"
    )
    parser.add_argument(
        "targets",
        nargs="*",
        default=list(DEFAULT_TARGETS),
        help="Hosts to traceroute (default: one.one.one.one google.com)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=8800, help="Dashboard port")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Simulate multi-hop routes with packet loss and WHOIS instead of live traceroute",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Seconds between re-traces (default: 45 live / 3 demo)",
    )
    parser.add_argument(
        "--probes",
        type=int,
        default=5,
        help="Probes per hop for packet-loss percentage (default: 5)",
    )
    parser.add_argument(
        "--speedtest-on-start",
        action="store_true",
        help="Run a speed test once the dashboard is up",
    )
    parser.add_argument(
        "--no-auto-demo-fallback",
        action="store_true",
        help="Exit if live traceroute fails instead of switching to demo mode",
    )
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the dashboard in the default browser (used by path_radar.command on macOS)",
    )
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    asyncio.run(run(args))


async def run(args: argparse.Namespace) -> None:
    interval = args.interval if args.interval is not None else (3.0 if args.demo else 45.0)
    state = RadarState(demo_mode=args.demo)
    app = create_app(state)

    tracer_task = asyncio.create_task(
        _run_tracer(
            state=state,
            targets=list(args.targets),
            force_demo=args.demo,
            auto_demo_fallback=not args.no_auto_demo_fallback,
            interval=interval,
            probes=max(1, min(args.probes, 10)),
        ),
        name="trace-radar",
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

    print(f"Trace radar dashboard: http://{args.host}:{chosen_port}")
    if args.demo:
        print("Running in demo mode: scripted routes with packet-loss % and WHOIS ownership data.")
    else:
        print("Running live traceroute with GeoIP + RDAP WHOIS; auto demo fallback if unavailable.")

    if args.open and not args.no_open:
        asyncio.create_task(_open_dashboard(args.host, chosen_port), name="open-browser")

    # Fire-and-forget: must not be in the wait set or a finished speed test
    # would tear down the dashboard (asyncio.wait FIRST_COMPLETED).
    if args.speedtest_on_start:
        asyncio.create_task(_delayed_speedtest(state), name="startup-speedtest")

    done, pending = await asyncio.wait(
        {tracer_task, server_task, stop_task},
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


async def _delayed_speedtest(state: RadarState) -> None:
    await asyncio.sleep(1.5)
    await run_speed_test(state)


async def _open_dashboard(host: str, port: int) -> None:
    url = f"http://{host}:{port}"
    for _ in range(40):
        if not _port_is_available(host, port):
            open_dashboard(url)
            return
        await asyncio.sleep(0.15)


def open_dashboard(url: str) -> None:
    """Open a URL in the default browser; prefer macOS ``open`` on Darwin."""
    if sys.platform == "darwin":
        subprocess.Popen(
            ["/usr/bin/open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    webbrowser.open(url)


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


async def _run_tracer(
    *,
    state: RadarState,
    targets: list[str],
    force_demo: bool,
    auto_demo_fallback: bool,
    interval: float,
    probes: int,
) -> None:
    if force_demo:
        state.demo_mode = True
        await DemoTracerBackend(state, targets=targets, interval=interval, probes=probes).run()
        return

    try:
        await LiveTracerBackend(state, targets=targets, interval=interval, probes=probes).run()
    except Exception as exc:
        message = (
            f"Live traceroute unavailable ({type(exc).__name__}: {exc}). Switching to demo tracer."
        )
        LOGGER.warning(message)
        await state.add_system_event("tracer-fallback", message)
        if not auto_demo_fallback:
            raise
        print(message)
        state.demo_mode = True
        await DemoTracerBackend(state, targets=targets, interval=min(interval, 3.0), probes=probes).run()


if __name__ == "__main__":
    main()
