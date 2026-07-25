"""Terminal CLI for live Bluetooth scanning."""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from .classic_scanner import scan_classic_devices
from .export import export_devices_csv, export_snapshot_json
from .scanner import BleakScannerBackend
from .signal_quality import device_type_label, rssi_stats, signal_quality_label
from .state import ControllerState, ToyObservation


def build_scan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan nearby Bluetooth devices from the terminal")
    parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds")
    parser.add_argument("--duration", type=float, default=0.0, help="Stop after N seconds (0 = run until Ctrl+C)")
    parser.add_argument("--stale-after", type=float, default=20.0, help="Seconds before a device is marked left")
    parser.add_argument("--min-rssi", type=int, default=-127, help="Hide devices weaker than this RSSI")
    parser.add_argument(
        "--device-type",
        choices=["all", "adorime_thruster", "ble_peripheral", "phone", "wearable", "input_device", "audio", "unknown"],
        default="all",
        help="Filter by inferred device type",
    )
    parser.add_argument("--classic", action="store_true", help="Also scan classic Bluetooth via bluetoothctl")
    parser.add_argument("--export", metavar="PATH", help="Write JSON snapshot on exit")
    parser.add_argument("--export-csv", metavar="PATH", help="Write CSV device list on exit")
    parser.add_argument("--plot", metavar="PATH", help="Save matplotlib RSSI plot for strongest device")
    parser.add_argument("--log-level", default="warning", choices=["debug", "info", "warning", "error"])
    return parser


async def run_scan(args: argparse.Namespace) -> int:
    state = ControllerState(stale_after=args.stale_after)
    scanner = BleakScannerBackend(state)
    scanner_task = asyncio.create_task(scanner.run(), name="cli-scanner")
    started = datetime.now(UTC)
    last_print = 0.0

    try:
        while True:
            await asyncio.sleep(max(0.2, args.interval))
            await state.mark_stale()
            now = datetime.now(UTC).timestamp()
            if now - last_print >= args.interval:
                last_print = now
                snapshot = await state.snapshot()
                _print_table(snapshot, min_rssi=args.min_rssi, device_type=args.device_type)
            if args.duration > 0 and (datetime.now(UTC) - started).total_seconds() >= args.duration:
                break
    except asyncio.CancelledError:
        raise
    finally:
        scanner_task.cancel()
        with suppress(asyncio.CancelledError):
            await scanner_task

    if args.classic:
        classic_devices = await scan_classic_devices()
        if classic_devices:
            print("\nClassic Bluetooth devices:")
            for device in classic_devices:
                print(f"  {device.address:17}  {device.name}")

    snapshot = await state.snapshot()
    if args.export:
        with open(args.export, "w", encoding="utf-8") as handle:
            handle.write(export_snapshot_json(snapshot))
        print(f"Wrote JSON export to {args.export}")
    if args.export_csv:
        with open(args.export_csv, "w", encoding="utf-8") as handle:
            handle.write(export_devices_csv(snapshot))
        print(f"Wrote CSV export to {args.export_csv}")
    if args.plot:
        _save_plot(snapshot, args.plot)
        print(f"Wrote RSSI plot to {args.plot}")
    return 0


def _print_table(snapshot: dict[str, Any], *, min_rssi: int, device_type: str) -> None:
    toys = snapshot.get("toys", [])
    filtered = [
        toy
        for toy in toys
        if toy.get("present")
        and (toy.get("rssi") is None or toy["rssi"] >= min_rssi)
        and (device_type == "all" or toy.get("device_type") == device_type)
    ]
    filtered.sort(key=lambda item: item.get("rssi") if item.get("rssi") is not None else -999, reverse=True)
    print(f"\n[{snapshot['generated_at']}] {len(filtered)} device(s)")
    print(f"{'MAC':<18} {'Name':<22} {'RSSI':>6} {'Quality':<10} {'Type':<18} {'Services'}")
    print("-" * 96)
    for toy in filtered:
        stats = toy.get("signal_stats") or {}
        quality = stats.get("quality") or signal_quality_label(toy.get("rssi"))
        services = ", ".join((toy.get("service_uuids") or [])[:2])
        if len(toy.get("service_uuids") or []) > 2:
            services += "…"
        name = (toy.get("name") or toy.get("display_name") or "Unnamed")[:22]
        print(
            f"{toy.get('address','?'):<18} {name:<22} "
            f"{toy.get('rssi','?'):>6} {quality:<10} {toy.get('device_type','?'):<18} {services}"
        )


def _save_plot(snapshot: dict[str, Any], path: str) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("Install matplotlib to use --plot (pip install matplotlib)") from exc

    toys = [toy for toy in snapshot.get("toys", []) if toy.get("rssi_history")]
    if not toys:
        raise RuntimeError("No RSSI history available for plotting.")
    toys.sort(key=lambda item: item.get("rssi") if item.get("rssi") is not None else -999, reverse=True)
    device = toys[0]
    values = device["rssi_history"]
    fig, axis = plt.subplots(figsize=(10, 4))
    axis.plot(range(len(values)), values, marker="o", linewidth=1.5)
    axis.set_title(f"RSSI history — {device.get('name') or device.get('address')}")
    axis.set_xlabel("Sample")
    axis.set_ylabel("RSSI (dBm)")
    axis.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def scan_main(argv: list[str] | None = None) -> int:
    parser = build_scan_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run_scan(args))
    except KeyboardInterrupt:
        print("\nScan stopped.")
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
