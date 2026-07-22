"""Command-line entry for Shield Line threat-aware time sink."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
from contextlib import suppress

import uvicorn

from .state import ShieldState
from .web import create_app

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Shield Line: detect threatening messages and auto-reply with a "
            "time-wasting bot to keep an abusive contact occupied."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind address")
    parser.add_argument("--port", type=int, default=8775, help="Dashboard port (default: 8775)")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Play sample threatening messages into the chat every few seconds",
    )
    parser.add_argument("--demo-interval", type=float, default=8.0, help="Seconds between demo messages")
    parser.add_argument(
        "--no-auto-shield",
        action="store_true",
        help="Start in passive mode (detection only until you enable shield)",
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
    state = ShieldState(auto_shield=not args.no_auto_shield)
    app = create_app(state)

    demo_task: asyncio.Task | None = None
    if args.demo:
        demo_task = asyncio.create_task(_demo_loop(state, args.demo_interval), name="shield-demo")

    chosen_port = pick_available_port(args.host, args.port)
    if chosen_port != args.port:
        message = f"Port {args.port} is busy; using port {chosen_port} instead."
        print(message)
        await state.add_system_event("port-reassigned", message)

    config = uvicorn.Config(app, host=args.host, port=chosen_port, log_level=args.log_level)
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(), name="shield-dashboard")

    stop_event = asyncio.Event()
    stop_task = asyncio.create_task(stop_event.wait(), name="stop-wait")
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    print(f"Shield Line dashboard: http://{args.host}:{chosen_port}")
    if args.demo:
        print("Demo mode: injecting sample threatening lines on an interval.")
    print("POST /api/chat with {\"message\": \"...\"} to simulate inbound texts.")

    done, pending = await asyncio.wait(
        {server_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    server.should_exit = True
    if demo_task:
        demo_task.cancel()
    for task in pending:
        if task is not stop_task:
            task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        if task is not stop_task and (exc := task.exception()):
            raise exc


async def _demo_loop(state: ShieldState, interval: float) -> None:
    await state.add_system_event("demo", "Demo playback started.")
    while True:
        msg = await state.next_demo_message()
        if msg is None:
            await state.add_system_event("demo", "Demo script finished; looping.")
            await state.reset_session()
            continue
        await state.ingest_inbound(msg)
        await asyncio.sleep(max(2.0, interval))


if __name__ == "__main__":
    main()
