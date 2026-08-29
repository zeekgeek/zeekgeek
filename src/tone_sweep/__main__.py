"""Run the tone sweep dashboard."""

from __future__ import annotations

import argparse
import os
import socket

import uvicorn

from .sweep import SweepConfig
from .web import create_app


def build_parser() -> argparse.ArgumentParser:
    render_port = os.getenv("PORT")
    parser = argparse.ArgumentParser(description="Graphical 47–65 Hz slow tone sweep")
    parser.add_argument("--host", default="0.0.0.0" if render_port else "127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=int(render_port or 8810), help="Dashboard port")
    parser.add_argument("--sweep-seconds", type=float, default=90.0, help="Seconds for one 47–65 Hz pass")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        config = SweepConfig(sweep_seconds=args.sweep_seconds)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    chosen_port = pick_available_port(args.host, args.port)
    if chosen_port != args.port:
        print(f"Port {args.port} is busy; using port {chosen_port} instead.")
    print(f"Tone sweep dashboard: http://{args.host}:{chosen_port}")
    uvicorn.run(create_app(config), host=args.host, port=chosen_port, log_level=args.log_level)


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
