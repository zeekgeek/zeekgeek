"""Push live Mac (ioreg) or local samples to a remote mac_battery dashboard."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from .reader import (
    IORegBatteryReader,
    LinuxSysfsBatteryReader,
    open_reader,
    sample_to_payload,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect live battery sensor data and POST it to a mac_battery dashboard "
            "(/api/ingest). Run this on the MacBook; point --url at the dashboard host."
        )
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Dashboard base URL, e.g. http://127.0.0.1:8780 or http://cloud-host:8780",
    )
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between posts")
    parser.add_argument(
        "--source",
        choices=["auto", "ioreg", "sysfs", "demo"],
        default="auto",
        help="Local sensor backend used by the collector (default: auto)",
    )
    parser.add_argument("--once", action="store_true", help="Post a single sample and exit")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def _post(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/api/ingest",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    args = build_parser().parse_args()
    try:
        reader = open_reader(source=args.source, force_demo=args.source == "demo", auto_demo_fallback=False)
    except Exception as exc:
        # Prefer explicit backends when auto fails on Mac/Linux
        if args.source == "auto":
            try:
                reader = IORegBatteryReader()
                reader.read()
            except Exception:
                try:
                    reader = LinuxSysfsBatteryReader()
                    reader.read()
                except Exception as inner:
                    print(f"Unable to open local battery sensor: {inner}", file=sys.stderr)
                    print("Tip: on a Mac this uses ioreg; on Linux it uses /sys/class/power_supply.", file=sys.stderr)
                    raise SystemExit(1) from exc
        else:
            print(f"Unable to open local battery sensor: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    print(f"Collector source: {reader.name}")
    print(f"Posting to {args.url.rstrip('/')}/api/ingest every {args.interval}s")
    print("Ctrl+C to stop.")

    while True:
        try:
            sample = reader.read()
            # Tag so the dashboard shows this came from the collector path
            if sample.source in {"ioreg", "demo"} or sample.source.startswith("sysfs"):
                payload = sample_to_payload(sample)
                payload["source"] = f"collect:{sample.source}"
            else:
                payload = sample_to_payload(sample)
            result = _post(args.url, payload)
            print(
                f"posted {payload.get('source')} "
                f"{sample.voltage_v:.3f}V {sample.amperage_a:.3f}A {sample.watts:.1f}W "
                f"soc={sample.charge_percent} → {result.get('status', 'ok')}"
            )
        except urllib.error.URLError as exc:
            print(f"ingest failed: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"collect failed: {exc}", file=sys.stderr)
            if args.once:
                raise SystemExit(1) from exc
        if args.once:
            return
        time.sleep(max(0.2, args.interval))


if __name__ == "__main__":
    main()
