"""Shared live state for the battery dashboard."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque


@dataclass
class BatteryState:
    history_limit: int = 180
    latest: dict[str, Any] | None = None
    history: Deque[dict[str, Any]] = field(default_factory=deque)
    events: Deque[dict[str, Any]] = field(default_factory=deque)
    _subscribers: list[asyncio.Queue] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.history = deque(maxlen=self.history_limit)
        self.events = deque(maxlen=100)

    def update(self, report: dict[str, Any]) -> None:
        prev = self.latest
        self.latest = report
        electrical = report.get("electrical", {})
        charging = report.get("charging", {})
        self.history.append(
            {
                "timestamp": report.get("timestamp"),
                "voltage_v": electrical.get("voltage_v"),
                "amperage_a": electrical.get("amperage_a"),
                "watts": electrical.get("watts"),
                "charge_percent": charging.get("charge_percent"),
                "is_charging": charging.get("is_charging"),
            }
        )
        if prev is None:
            self._emit("started", "Battery monitor started")
        else:
            was = prev.get("charging", {}).get("is_charging")
            now = charging.get("is_charging")
            if was != now:
                self._emit(
                    "charge-state",
                    "Charging started" if now else "Charging stopped",
                )
            prev_pct = prev.get("charging", {}).get("charge_percent")
            now_pct = charging.get("charge_percent")
            if (
                isinstance(prev_pct, (int, float))
                and isinstance(now_pct, (int, float))
                and prev_pct < 80 <= now_pct
            ):
                self._emit("reached-80", "Reached 80% charge")
            if charging.get("fully_charged") and not prev.get("charging", {}).get("fully_charged"):
                self._emit("full", "Battery fully charged")

        for queue in list(self._subscribers):
            try:
                queue.put_nowait({"type": "snapshot", "data": report})
            except asyncio.QueueFull:
                pass

    def _emit(self, kind: str, message: str) -> None:
        event = {"type": kind, "message": message}
        if self.latest:
            event["timestamp"] = self.latest.get("timestamp")
        self.events.appendleft(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait({"type": "event", "data": event})
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def snapshot(self) -> dict[str, Any]:
        return {
            "latest": self.latest,
            "history": list(self.history),
            "events": list(self.events),
        }
