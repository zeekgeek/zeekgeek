"""Command-line entry point for the Bitcoin market radar."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import socket
from contextlib import suppress

import uvicorn

from .feed import DemoFeed, LiveFeed
from .state import MarketState
from .web import create_app

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bitcoin market radar: crypto board plus equity/macro health"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=8810, help="Dashboard port")
    parser.add_argument("--demo", action="store_true", help="Simulate quotes instead of polling live APIs")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=45.0,
        help="Seconds between live quote polls (demo uses 2s)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Fetch one snapshot, print JSON, and exit (no dashboard)",
    )
    parser.add_argument(
        "--no-auto-demo-fallback",
        action="store_true",
        help="Exit if live CoinGecko/Yahoo feeds fail instead of switching to demo mode",
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
    state = MarketState()
    if args.once:
        snapshot = await _one_shot(state, force_demo=args.demo, auto_fallback=not args.no_auto_demo_fallback)
        print(json.dumps(snapshot, indent=2, default=str))
        return

    app = create_app(state)
    feed_task = asyncio.create_task(
        _run_feed(
            state=state,
            force_demo=args.demo,
            auto_demo_fallback=not args.no_auto_demo_fallback,
            poll_interval=args.poll_interval,
        ),
        name="btc-feed",
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

    print(f"Bitcoin market radar: http://{args.host}:{chosen_port}")
    if args.demo:
        print("Running in demo mode: correlated crypto + equity tape with risk-on / risk-off episodes.")
    else:
        print("Polling CoinGecko + Yahoo Finance + alternative.me Fear & Greed (demo fallback if needed).")

    done, pending = await asyncio.wait(
        {feed_task, server_task, stop_task},
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


async def _one_shot(state: MarketState, *, force_demo: bool, auto_fallback: bool) -> dict:
    if force_demo:
        await state.ingest(await DemoFeed().fetch(), mode="demo")
        return await state.snapshot()
    try:
        await state.ingest(await LiveFeed().fetch(), mode="live")
        return await state.snapshot()
    except Exception as exc:
        message = f"Live market feed unavailable ({type(exc).__name__}: {exc})."
        if not auto_fallback:
            raise
        LOGGER.warning("%s Switching to demo.", message)
        await state.add_system_event("feed-fallback", message)
        await state.ingest(await DemoFeed().fetch(), mode="demo")
        return await state.snapshot()


async def _run_feed(
    *,
    state: MarketState,
    force_demo: bool,
    auto_demo_fallback: bool,
    poll_interval: float,
) -> None:
    if force_demo:
        await _loop_demo(state)
        return
    try:
        await _loop_live(state, poll_interval)
    except Exception as exc:
        message = f"Live market feed unavailable ({type(exc).__name__}: {exc}). Switching to demo quotes."
        LOGGER.warning(message)
        await state.add_system_event("feed-fallback", message)
        if not auto_demo_fallback:
            raise
        print(message)
        await _loop_demo(state)


async def _loop_live(state: MarketState, interval: float) -> None:
    feed = LiveFeed()
    first = await feed.fetch()
    await state.ingest(first, mode="live")
    while True:
        await asyncio.sleep(interval)
        try:
            snapshot = await feed.fetch()
        except Exception as exc:
            LOGGER.warning("Live poll failed (%s); keeping previous snapshot", exc)
            await state.add_system_event("poll-error", f"Live poll failed: {exc}")
            continue
        await state.ingest(snapshot, mode="live")


async def _loop_demo(state: MarketState) -> None:
    feed = DemoFeed()
    while True:
        await state.ingest(await feed.fetch(), mode="demo")
        await asyncio.sleep(2.0)


if __name__ == "__main__":
    main()
