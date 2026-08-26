"""Command-line entry point for Path Radar."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
from contextlib import suppress

import uvicorn

from .state import PathState
from .topology import DEFAULT_TARGET
from .tracer import DemoTraceBackend, LiveTraceBackend
from .web import create_app

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Path Radar: force-directed network map plus continuous traceroute "
            "(Scanny topology + PingPlotter hop latency)."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=8800, help="Dashboard port")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="Host or IP to trace")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between probes")
    parser.add_argument("--demo", action="store_true", help="Simulated LAN + multi-path internet (no traceroute binary)")
    parser.add_argument(
        "--no-auto-demo-fallback",
        action="store_true",
        help="Exit if live traceroute is unavailable instead of switching to demo mode",
    )
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


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


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    asyncio.run(run(args))


async def run(args: argparse.Namespace) -> None:
    state = PathState()
    await state.set_target(args.target)
    app = create_app(state)
    scanner_task = asyncio.create_task(
        _run_tracer(
            state=state,
            force_demo=args.demo,
            auto_demo_fallback=not args.no_auto_demo_fallback,
            interval=args.interval,
        ),
        name="path-tracer",
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

    print(f"Path Radar dashboard: http://{args.host}:{chosen_port}")
    if args.demo:
        print("Running in demo mode: LAN map + Comcast/Cogent/Google paths with a congested peering hop.")
    else:
        print("Running live traceroute with automatic demo fallback if unavailable.")

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


async def _run_tracer(
    *,
    state: PathState,
    force_demo: bool,
    auto_demo_fallback: bool,
    interval: float,
) -> None:
    if force_demo:
        await DemoTraceBackend(state, interval=interval).run()
        return
    try:
        await LiveTraceBackend(state, interval=max(2.0, interval)).run()
    except Exception as exc:
        message = f"Live traceroute unavailable ({type(exc).__name__}: {exc}). Switching to demo scanner."
        LOGGER.warning(message)
        await state.add_system_event("scanner-fallback", message)
        if not auto_demo_fallback:
            raise
        print(message)
        await DemoTraceBackend(state, interval=interval).run()


if __name__ == "__main__":
    main()
