#!/usr/bin/env python3
"""BluetoothRadar command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Iterable

import pandas as pd
from rich.console import Console, Group
from rich.live import Live
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from analysis import GraphReport, analyze_graph
from graph import build_relationship_graph, show_interactive_graph
from scanner import BluetoothRadarScanner, DiscoveredDevice, demo_scan


console = Console()


def device_table(
    devices: Iterable[DiscoveredDevice], sort_by: str = "rssi"
) -> Table:
    table = Table(title="Live BLE advertisements", expand=True)
    table.add_column("Flag")
    table.add_column("Identifier", overflow="fold")
    table.add_column("Name")
    table.add_column("RSSI", justify="right")
    table.add_column("TX", justify="right")
    table.add_column("Manufacturer / frame")
    table.add_column("Services", overflow="fold")
    items = list(devices)
    key_functions = {
        "address": lambda item: item.address,
        "name": lambda item: item.name or "",
        "rssi": lambda item: -item.rssi,
        "last_seen": lambda item: -item.last_seen,
    }
    items.sort(key=key_functions[sort_by])
    for device in items:
        manufacturers = ", ".join(
            f"{record.company}"
            + (f" ({record.frame_type})" if record.frame_type else "")
            for record in device.manufacturer_data
        )
        style = "bold red" if device.identity_limited else None
        table.add_row(
            "🕵️ Hidden" if device.identity_limited else "",
            device.address,
            device.display_name,
            str(device.rssi),
            "" if device.tx_power is None else str(device.tx_power),
            manufacturers or "—",
            "\n".join(sorted(device.service_uuids)) or "—",
            style=style,
        )
    return table


def print_report(report: GraphReport, graph_nodes: dict[str, dict]) -> None:
    table = Table(title="Relationship intelligence")
    table.add_column("Finding")
    table.add_column("Result")
    hubs = ", ".join(
        f'{graph_nodes[node]["label"]} ({score:.2f})'
        for node, score in report.hubs
    )
    cluster_text = " | ".join(
        ", ".join(graph_nodes[node]["label"] for node in sorted(cluster))
        for cluster in report.clusters
    )
    table.add_row("Hub candidates", hubs or "none")
    table.add_row("Clusters", cluster_text or "none")
    table.add_row(
        "Multiple overlapping clusters",
        ", ".join(report.multi_cluster_devices) or "none",
    )
    console.print(table)
    for suggestion in report.suggestions:
        console.print(f"[cyan]Hypothesis:[/] {suggestion}")


async def run(args: argparse.Namespace) -> int:
    observed: dict[str, DiscoveredDevice] = {}
    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TimeRemainingColumn(),
    )
    task = progress.add_task("Scanning", total=args.duration)

    def update(device: DiscoveredDevice) -> None:
        observed[device.address] = device

    with Live(
        Group(progress, device_table(observed.values(), args.sort)),
        console=console,
        refresh_per_second=6,
    ) as live:
        async def refresh() -> None:
            loop = asyncio.get_running_loop()
            started = loop.time()
            while not scan_task.done():
                elapsed = min(args.duration, loop.time() - started)
                progress.update(task, completed=elapsed)
                live.update(
                    Group(progress, device_table(observed.values(), args.sort))
                )
                await asyncio.sleep(0.15)

        if args.demo:
            scan_task = asyncio.create_task(demo_scan(args.duration, update))
        else:
            scanner = BluetoothRadarScanner(
                active=args.scan_mode == "active",
                adapter=args.adapter,
                on_update=update,
            )
            scan_task = asyncio.create_task(scanner.scan(args.duration))
        refresh_task = asyncio.create_task(refresh())
        try:
            devices = await scan_task
        finally:
            await refresh_task
        observed.update({device.address: device for device in devices})
        progress.update(task, completed=args.duration)
        live.update(Group(progress, device_table(observed.values(), args.sort)))

    devices = list(observed.values())
    if args.json:
        Path(args.json).write_text(
            json.dumps([item.as_dict() for item in devices], indent=2),
            encoding="utf-8",
        )
    if args.csv:
        pd.json_normalize([item.as_dict() for item in devices]).to_csv(
            args.csv, index=False
        )

    relationship_graph = build_relationship_graph(devices)
    report = analyze_graph(relationship_graph)
    print_report(report, relationship_graph.nodes)
    if args.gui:
        show_interactive_graph(relationship_graph)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Observe local BLE advertisements and build explicitly heuristic "
            "relationship hypotheses."
        )
    )
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument(
        "--scan-mode", choices=("active", "passive"), default="active"
    )
    parser.add_argument("--adapter", help="Linux BlueZ adapter, e.g. hci0")
    parser.add_argument("--sort", choices=("rssi", "name", "address", "last_seen"), default="rssi")
    parser.add_argument("--demo", action="store_true", help="use deterministic sample data")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="serve a live browser dashboard (real BLE by default)",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="open the desktop radar dashboard with live Bluetooth scanning",
    )
    parser.add_argument(
        "--demo-fallback",
        action="store_true",
        help="browser mode: allow simulated devices when no Bluetooth adapter is found",
    )
    parser.add_argument(
        "--no-demo-fallback",
        action="store_true",
        help="browser mode: never use simulated devices; keep LIVE error state",
    )
    parser.add_argument(
        "--no-auto-demo-fallback",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--open-browser",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="open the dashboard URL in the default browser",
    )
    parser.add_argument(
        "--gui",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="show the clickable Matplotlib graph",
    )
    parser.add_argument("--json", metavar="PATH", help="export full observations")
    parser.add_argument("--csv", metavar="PATH", help="export observations as CSV")
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        if args.desktop:
            args.browser = True
            args.open_browser = True
            args.demo = False
            args.no_demo_fallback = True
        if args.browser:
            from web import run_dashboard

            return run_dashboard(args)
        return asyncio.run(run(args))
    except (ValueError, RuntimeError, OSError) as error:
        console.print(f"[bold red]Scan failed:[/] {error}")
        return 2
    except KeyboardInterrupt:
        console.print("\n[yellow]Scan stopped.[/]")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

