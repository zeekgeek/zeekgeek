"""Command-line entry point for MacBook battery diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
import sys
import time
from contextlib import suppress

import uvicorn

from .display import print_live, render_snapshot
from .metrics import ChargeRateTracker, build_report
from .reader import RemoteIngestBuffer, WaitingForSensor, open_reader
from .state import BatteryState
from .web import create_app

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Realtime MacBook battery diagnostic: charging voltage, watts, amperage, "
            "health, cycles, and ETA to 80% / full. Supports local ioreg, Linux sysfs, "
            "SSH pull from a Mac, or remote ingest from mac_battery.collect."
        )
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print a single snapshot and exit (no live refresh / dashboard)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between samples (default: 1.0)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Dashboard bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8780,
        help="Dashboard port (default: 8780)",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Terminal-only live monitor (skip the web dashboard)",
    )
    parser.add_argument(
        "--no-terminal",
        action="store_true",
        help="Dashboard only (skip clearing/redrawing the terminal)",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "ioreg", "sysfs", "ssh", "remote", "demo"],
        default="auto",
        help=(
            "Sensor backend: auto (ioreg→sysfs→ssh→demo), ioreg, sysfs, "
            "ssh, remote (HTTP ingest), or demo"
        ),
    )
    parser.add_argument(
        "--ssh",
        default=None,
        metavar="USER@HOST",
        help="Mac SSH target for --source ssh (or auto fallback), e.g. user@macbook.local",
    )
    parser.add_argument(
        "--sysfs-root",
        default="/sys/class/power_supply",
        help="Linux power_supply path (default: /sys/class/power_supply)",
    )
    parser.add_argument("--demo", action="store_true", help="Shortcut for --source demo")
    parser.add_argument(
        "--no-auto-demo-fallback",
        action="store_true",
        help="Exit if no live sensor backend is available (do not use demo)",
    )
    parser.add_argument(
        "--target",
        type=float,
        default=80.0,
        help="Optimized charge target percent for ETA (default: 80)",
    )
    parser.add_argument("--log-level", default="warning", choices=["debug", "info", "warning", "error"])
    return parser


def pick_available_port(host: str, preferred: int, max_tries: int = 30) -> int:
    port = preferred
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                port += 1
                continue
            return port
    raise RuntimeError(f"No free port found near {preferred}")


def _source_label(reader) -> str:
    name = getattr(reader, "name", type(reader).__name__)
    if name == "DemoBatteryReader":
        return "demo (simulated)"
    if name == "IORegBatteryReader":
        return "live macOS ioreg / AppleSmartBattery"
    if name == "LinuxSysfsBatteryReader":
        return f"live Linux sysfs ({getattr(reader, 'path', 'BAT*')})"
    if name == "SshIORegBatteryReader":
        return f"live SSH ioreg ({getattr(reader, 'target', '?')})"
    if name == "RemoteIngestBuffer":
        return "remote ingest (waiting for mac_battery.collect)"
    return name


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))

    source = "demo" if args.demo else args.source
    ingest: RemoteIngestBuffer | None = RemoteIngestBuffer() if source == "remote" else None

    try:
        reader = open_reader(
            source=source,
            force_demo=args.demo,
            auto_demo_fallback=not args.no_auto_demo_fallback,
            ssh_target=args.ssh,
            sysfs_root=args.sysfs_root,
            ingest=ingest,
        )
    except Exception as exc:
        print(f"Unable to open battery reader: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if isinstance(reader, RemoteIngestBuffer):
        ingest = reader

    if args.once:
        if isinstance(reader, RemoteIngestBuffer):
            print(
                "Remote source needs a live collector; --once is not supported with --source remote.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        try:
            sample = reader.read()
        except WaitingForSensor as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc
        rate = ChargeRateTracker()
        rate.add(sample.amperage_ma)
        report = build_report(sample, rate, target_optimized=args.target)
        print(render_snapshot(report))
        if report["source"] == "demo" and not args.demo:
            print("\n(Note: demo fallback — no local/SSH battery sensor found.)")
        return

    asyncio.run(run_live(args, reader, ingest=ingest))


async def run_live(args: argparse.Namespace, reader, *, ingest: RemoteIngestBuffer | None) -> None:
    state = BatteryState()
    rate = ChargeRateTracker()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    sampler = asyncio.create_task(
        _sample_loop(reader, state, rate, args.interval, args.target, stop_event),
        name="battery-sampler",
    )

    server_task = None
    chosen_port = args.port
    if not args.no_web:
        chosen_port = pick_available_port(args.host, args.port)
        if chosen_port != args.port:
            print(f"Port {args.port} is busy; using port {chosen_port} instead.")
        app = create_app(state, ingest=ingest)
        config = uvicorn.Config(app, host=args.host, port=chosen_port, log_level=args.log_level)
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve(), name="battery-dashboard")
        print(f"Battery dashboard: http://{args.host}:{chosen_port}")

    print(f"Sensor backend: {_source_label(reader)}")
    if ingest is not None:
        print(
            "Remote ingest ready. On the MacBook run:\n"
            f"  python3 -m mac_battery.collect --url http://<reachable-host>:{chosen_port}"
        )

    terminal_task = None
    if not args.no_terminal:
        terminal_task = asyncio.create_task(
            _terminal_loop(state, stop_event, args.interval),
            name="terminal-ui",
        )
    else:
        print("Terminal UI disabled; use the dashboard URL above.")

    await stop_event.wait()
    sampler.cancel()
    if terminal_task:
        terminal_task.cancel()
    if server_task:
        server_task.cancel()
    with suppress(asyncio.CancelledError):
        await sampler
        if terminal_task:
            await terminal_task
        if server_task:
            await server_task


async def _sample_loop(reader, state, rate, interval, target, stop_event) -> None:
    waiting_notified = False
    while not stop_event.is_set():
        try:
            sample = await asyncio.to_thread(reader.read)
            rate.add(sample.amperage_ma)
            report = build_report(sample, rate, target_optimized=target)
            state.update(report)
            waiting_notified = False
        except WaitingForSensor as exc:
            if not waiting_notified:
                LOGGER.warning("%s", exc)
                waiting_notified = True
        except Exception:
            LOGGER.exception("Failed to sample battery")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.2, interval))
        except asyncio.TimeoutError:
            continue


async def _terminal_loop(state: BatteryState, stop_event: asyncio.Event, interval: float) -> None:
    deadline = time.monotonic() + 5
    while state.latest is None and time.monotonic() < deadline and not stop_event.is_set():
        await asyncio.sleep(0.05)
    while not stop_event.is_set():
        if state.latest:
            print_live(state.latest, clear=True)
        else:
            print_live(
                {
                    "timestamp": "",
                    "source": "waiting",
                    "electrical": {
                        "voltage_v": 0,
                        "voltage_mv": 0,
                        "amperage_a": 0,
                        "amperage_ma": 0,
                        "watts": 0,
                        "temperature_c": 0,
                        "smoothed_amperage_ma": None,
                    },
                    "charging": {
                        "adapter_connected": False,
                        "is_charging": False,
                        "fully_charged": False,
                        "charge_percent": None,
                        "apple_time_remaining_min": None,
                        "eta_to_80_label": "—",
                        "eta_to_full_label": "—",
                    },
                    "health": {
                        "design_capacity_mah": 0,
                        "max_capacity_mah": 0,
                        "current_capacity_mah": 0,
                        "health_percent": None,
                        "health_band": "waiting for sensor",
                        "cycle_count": 0,
                        "design_cycle_count": 1000,
                        "cycle_life_used_percent": None,
                        "cycle_band": "—",
                        "serial": "",
                        "device_name": "",
                        "manufacturer": "",
                    },
                },
                clear=True,
            )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.2, interval))
        except asyncio.TimeoutError:
            continue


if __name__ == "__main__":
    main()
