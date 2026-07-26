"""Export scan snapshots and connection logs."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def export_snapshot_json(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=False)


def export_devices_csv(snapshot: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "address",
            "name",
            "device_type",
            "transport",
            "rssi",
            "rssi_average",
            "rssi_min",
            "rssi_max",
            "signal_quality",
            "present",
            "controllable",
            "brand",
            "first_seen",
            "last_seen",
            "service_uuids",
        ]
    )
    for toy in snapshot.get("toys", []):
        stats = toy.get("signal_stats") or {}
        writer.writerow(
            [
                toy.get("address"),
                toy.get("name") or toy.get("display_name"),
                toy.get("device_type"),
                toy.get("transport", "ble"),
                toy.get("rssi"),
                stats.get("average"),
                stats.get("min"),
                stats.get("max"),
                stats.get("quality"),
                toy.get("present"),
                toy.get("controllable"),
                toy.get("brand"),
                toy.get("first_seen"),
                toy.get("last_seen"),
                ";".join(toy.get("service_uuids") or []),
            ]
        )
    return buffer.getvalue()


def export_connection_logs_csv(events: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["timestamp", "type", "address", "name", "message"])
    connection_types = {
        "connected",
        "disconnected",
        "control",
        "pattern-error",
        "scanner-error",
        "scanner-deep-scan",
        "gatt-deep-scan",
    }
    for event in events:
        if event.get("type") not in connection_types and event.get("address") != "system":
            continue
        writer.writerow(
            [
                event.get("at"),
                event.get("type"),
                event.get("address"),
                event.get("name"),
                event.get("message"),
            ]
        )
    return buffer.getvalue()
