"""In-memory route traces, per-hop RTT history, and speed test state."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .analysis import annotate_hops, problem_cards
from .geoip import GeoInfo
from .graph import SAMPLE_LAN, build_topology
from .whois import WhoisInfo


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def loss_percent(sent: int, answered: int) -> float:
    """Packet-loss percentage for a probe window (0–100)."""
    if sent <= 0:
        return 0.0
    return round(100.0 * max(0, sent - answered) / sent, 1)


@dataclass
class HopObservation:
    """One hop from a single traceroute pass."""

    ttl: int
    ip: str | None
    rtts_ms: list[float] = field(default_factory=list)
    probes: int = 3
    hostname: str | None = None
    geo: GeoInfo | None = None
    whois: WhoisInfo | None = None

    @property
    def responded(self) -> bool:
        return self.ip is not None

    @property
    def loss_pct(self) -> float:
        return loss_percent(self.probes, len(self.rtts_ms))


@dataclass
class Hop:
    """A hop position on a route, accumulated across trace cycles."""

    ttl: int
    ip: str | None
    hostname: str | None = None
    geo: GeoInfo | None = None
    whois: WhoisInfo | None = None
    probes_sent: int = 0
    probes_answered: int = 0
    last_probes: int = 0
    last_answered: int = 0
    last_loss_pct: float = 0.0
    last_rtts: list[float] = field(default_factory=list)
    rtt_history: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    loss_history: deque[float] = field(default_factory=lambda: deque(maxlen=60))
    # PingPlotter-style per-cycle samples: {at, rtt_avg_ms, loss_pct, answered, probes}
    timeline: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=120))

    def update(self, obs: HopObservation, *, at: datetime | None = None) -> None:
        self.ip = obs.ip
        if obs.hostname:
            self.hostname = obs.hostname
        if obs.geo is not None:
            self.geo = obs.geo
        if obs.whois is not None:
            self.whois = obs.whois
        self.probes_sent += obs.probes
        self.probes_answered += len(obs.rtts_ms)
        self.last_probes = obs.probes
        self.last_answered = len(obs.rtts_ms)
        self.last_loss_pct = obs.loss_pct
        self.last_rtts = list(obs.rtts_ms)
        self.rtt_history.extend(obs.rtts_ms)
        self.loss_history.append(obs.loss_pct)
        avg = round(sum(obs.rtts_ms) / len(obs.rtts_ms), 2) if obs.rtts_ms else None
        self.timeline.append(
            {
                "at": iso_time(at or utc_now()),
                "rtt_avg_ms": avg,
                "rtt_min_ms": round(min(obs.rtts_ms), 2) if obs.rtts_ms else None,
                "rtt_max_ms": round(max(obs.rtts_ms), 2) if obs.rtts_ms else None,
                "loss_pct": obs.loss_pct,
                "answered": len(obs.rtts_ms),
                "probes": obs.probes,
                "ip": obs.ip,
            }
        )

    def snapshot(self) -> dict[str, Any]:
        history = list(self.rtt_history)
        cumulative_loss = loss_percent(self.probes_sent, self.probes_answered)
        geo = self.geo.to_dict() if self.geo is not None else None
        whois = self.whois.to_dict() if self.whois is not None else None
        # Health label for the live hop view (green / amber / red).
        if self.ip is None and self.probes_sent > 0:
            health = "down"
        elif self.last_loss_pct >= 20 or (history and history[-1] > 200):
            health = "poor"
        elif self.last_loss_pct > 0 or (history and max(history[-5:] or [0]) > 100):
            health = "degraded"
        elif self.ip is None:
            health = "unknown"
        else:
            health = "good"
        return {
            "ttl": self.ttl,
            "ip": self.ip,
            "hostname": self.hostname,
            "responded": self.ip is not None,
            "health": health,
            "geo": geo,
            "whois": whois,
            "located": bool(self.geo is not None and self.geo.located),
            "is_private": bool(self.geo is not None and self.geo.is_private),
            "rtt_last_ms": round(self.last_rtts[-1], 2) if self.last_rtts else None,
            "rtt_min_ms": round(min(history), 2) if history else None,
            "rtt_avg_ms": round(sum(history) / len(history), 2) if history else None,
            "rtt_max_ms": round(max(history), 2) if history else None,
            "probes_sent": self.probes_sent,
            "probes_answered": self.probes_answered,
            "last_probes": self.last_probes,
            "last_answered": self.last_answered,
            "last_loss_pct": self.last_loss_pct,
            "loss_pct": cumulative_loss,
            "loss_history": [round(value, 1) for value in self.loss_history],
            "rtt_history": [round(value, 2) for value in history[-40:]],
            "timeline": list(self.timeline),
        }


@dataclass
class RouteTrace:
    """All accumulated knowledge about the path to one target."""

    target: str
    resolved_ip: str | None = None
    status: str = "pending"  # pending | active | failed
    hops: list[Hop] = field(default_factory=list)
    destination_reached: bool = False
    trace_count: int = 0
    first_traced: datetime | None = None
    last_traced: datetime | None = None
    error: str | None = None

    def signature(self) -> tuple[str, ...]:
        return tuple(hop.ip or "*" for hop in self.hops)

    def snapshot(self) -> dict[str, Any]:
        hops = annotate_hops([hop.snapshot() for hop in self.hops])
        answered = [h for h in hops if h["responded"]]
        probes_sent = sum(h["probes_sent"] for h in hops)
        probes_answered = sum(h["probes_answered"] for h in hops)
        lossy = [h for h in hops if h["loss_pct"] > 0]
        problems = problem_cards(hops)
        return {
            "target": self.target,
            "resolved_ip": self.resolved_ip,
            "status": self.status,
            "destination_reached": self.destination_reached,
            "trace_count": self.trace_count,
            "first_traced": iso_time(self.first_traced) if self.first_traced else None,
            "last_traced": iso_time(self.last_traced) if self.last_traced else None,
            "error": self.error,
            "hop_count": len(hops),
            "located_count": sum(1 for h in hops if h["located"]),
            "whois_count": sum(1 for h in hops if h.get("whois") and h["whois"].get("found")),
            "end_to_end_ms": answered[-1]["rtt_avg_ms"] if answered else None,
            "probes_sent": probes_sent,
            "probes_answered": probes_answered,
            "packet_loss_pct": loss_percent(probes_sent, probes_answered),
            "lossy_hop_count": len(lossy),
            "slow_hop_count": sum(1 for h in hops if h.get("slow")),
            "problems": problems,
            "hops": hops,
        }


def _idle_speedtest() -> dict[str, Any]:
    return {
        "status": "idle",
        "phase": None,
        "progress": 0,
        "latency_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": None,
        "download_mbps": None,
        "upload_mbps": None,
        "current_mbps": None,
        "server": None,
        "message": None,
        "started_at": None,
        "finished_at": None,
    }


class RadarState:
    """Shared state between the tracer backend and the web dashboard."""

    def __init__(self, *, demo_mode: bool = False, max_events: int = 300) -> None:
        self.demo_mode = demo_mode
        self._routes: dict[str, RouteTrace] = {}
        self._order: list[str] = []
        self._origin: GeoInfo | None = None
        self._speedtest: dict[str, Any] = _idle_speedtest()
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._new_targets: asyncio.Queue[str] = asyncio.Queue()
        self._tool_results: deque[dict[str, Any]] = deque(maxlen=40)
        self._lock = asyncio.Lock()

    async def request_trace(self, target: str) -> bool:
        """Register a target and queue a probe.

        Returns True when the target is newly added, False when it was already
        tracked (a re-trace is still queued so Trace route always refreshes).
        """
        target = target.strip()
        if not target:
            return False
        created = False
        async with self._lock:
            if target not in self._routes:
                self._routes[target] = RouteTrace(target=target)
                self._order.append(target)
                created = True
            self._events.append(
                self._system_event(
                    "trace-requested",
                    f"{'Tracing' if created else 'Re-tracing'} route to {target}…",
                    target=target,
                )
            )
        await self._new_targets.put(target)
        return created

    async def next_new_target(self, timeout: float) -> str | None:
        """Backends poll this to pick up user-requested targets promptly."""
        try:
            return await asyncio.wait_for(self._new_targets.get(), timeout=timeout)
        except TimeoutError:
            return None

    async def known_targets(self) -> list[str]:
        async with self._lock:
            return list(self._order)

    async def set_origin(self, geo: GeoInfo | None) -> None:
        async with self._lock:
            self._origin = geo
            if geo is not None and geo.located:
                self._events.append(
                    self._system_event("origin-located", f"Trace origin located: {geo.place_label()}")
                )

    async def ingest_trace(
        self,
        target: str,
        *,
        resolved_ip: str | None,
        hops: list[HopObservation],
        destination_reached: bool,
        error: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            now = utc_now()
            emitted: list[dict[str, Any]] = []
            route = self._routes.get(target)
            if route is None:
                route = RouteTrace(target=target)
                self._routes[target] = route
                self._order.append(target)

            if error is not None:
                route.status = "failed"
                route.error = error
                route.last_traced = now
                emitted.append(self._system_event("trace-failed", f"Trace to {target} failed: {error}", target=target))
                self._events.extend(emitted)
                return emitted

            previous_signature = route.signature() if route.trace_count else None
            route.resolved_ip = resolved_ip
            route.status = "active"
            route.error = None
            route.destination_reached = destination_reached
            route.trace_count += 1
            route.last_traced = now
            if route.first_traced is None:
                route.first_traced = now

            for obs in hops:
                index = obs.ttl - 1
                while len(route.hops) <= index:
                    route.hops.append(Hop(ttl=len(route.hops) + 1, ip=None))
                hop = route.hops[index]
                if hop.ip is not None and obs.ip is not None and hop.ip != obs.ip:
                    # Path changed at this TTL: reset accumulated stats for the new router.
                    route.hops[index] = hop = Hop(ttl=obs.ttl, ip=obs.ip)
                hop.update(obs, at=now)
            del route.hops[len(hops):]

            if previous_signature is None:
                located = sum(1 for hop in route.hops if hop.geo is not None and hop.geo.located)
                emitted.append(
                    self._system_event(
                        "route-mapped",
                        f"Route to {target} mapped: {len(route.hops)} hops, {located} geolocated"
                        + ("" if destination_reached else " (destination did not answer)"),
                        target=target,
                    )
                )
            elif previous_signature != route.signature():
                emitted.append(
                    self._system_event("route-changed", f"Route to {target} changed path", target=target)
                )

            self._events.extend(emitted)
            return emitted

    async def update_speedtest(self, *, finished: bool = False, **fields: Any) -> dict[str, Any]:
        async with self._lock:
            # Fresh run (or live→demo restart): reset gauges when latency phase begins.
            starting = fields.get("status") == "running" and fields.get("phase") == "latency"
            if starting:
                self._speedtest = _idle_speedtest()
                self._speedtest["started_at"] = iso_time(utc_now())
            self._speedtest.update(fields)
            if finished or fields.get("status") in {"complete", "failed"}:
                self._speedtest["finished_at"] = iso_time(utc_now())
            if fields.get("status") == "complete" or (finished and self._speedtest["status"] == "running"):
                self._speedtest["status"] = "complete"
                st = self._speedtest
                self._events.append(
                    self._system_event(
                        "speedtest-complete",
                        f"Speed test: ↓ {st['download_mbps']} Mbps · ↑ {st['upload_mbps']} Mbps · "
                        f"{st['latency_ms']} ms latency · {st['jitter_ms']} ms jitter",
                    )
                )
            elif fields.get("status") == "failed":
                self._events.append(
                    self._system_event("speedtest-failed", fields.get("message") or "Speed test failed")
                )
            return dict(self._speedtest)

    async def speedtest_running(self) -> bool:
        async with self._lock:
            return self._speedtest["status"] == "running"

    async def add_system_event(self, event_type: str, message: str) -> dict[str, Any]:
        async with self._lock:
            event = self._system_event(event_type, message)
            self._events.append(event)
            return event

    async def record_tool_result(self, tool: str, target: str, result: dict[str, Any]) -> dict[str, Any]:
        """Store a Scanny-style tool result and emit an event for the live feed."""
        async with self._lock:
            entry = {
                "tool": tool,
                "target": target,
                "at": iso_time(utc_now()),
                "result": result,
            }
            self._tool_results.appendleft(entry)
            summary = _tool_summary(tool, target, result)
            self._events.append(self._system_event(f"tool:{tool}", summary, target=target))
            return entry

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            now = utc_now()
            routes = [self._routes[target].snapshot() for target in self._order]
            located_hops = sum(route["located_count"] for route in routes)
            total_hops = sum(route["hop_count"] for route in routes)
            origin = self._origin.to_dict() if self._origin is not None else None
            return {
                "generated_at": iso_time(now),
                "demo_mode": self.demo_mode,
                "origin": origin,
                "target_count": len(routes),
                "hop_count": total_hops,
                "located_count": located_hops,
                "slow_hop_count": sum(route.get("slow_hop_count", 0) for route in routes),
                "routes": routes,
                "graph": build_topology(routes, origin=origin, lan=SAMPLE_LAN),
                "speedtest": dict(self._speedtest),
                "tool_results": list(self._tool_results),
                "events": list(self._events),
            }

    def _system_event(self, event_type: str, message: str, *, target: str | None = None) -> dict[str, Any]:
        return {
            "type": event_type,
            "target": target or "system",
            "message": message,
            "at": iso_time(utc_now()),
        }


def _tool_summary(tool: str, target: str, result: dict[str, Any]) -> str:
    if tool == "dns":
        records = result.get("records") or {}
        kinds = ", ".join(f"{k}:{len(v)}" for k, v in records.items()) or "no records"
        return f"DNS {target}: {kinds}"
    if tool == "whois":
        if result.get("found"):
            return f"WHOIS {target}: {result.get('org') or result.get('name') or result.get('handle')}"
        return f"WHOIS {target}: {result.get('error') or 'no record'}"
    if tool == "ports":
        open_ports = result.get("open_ports") or []
        return f"Port scan {target}: {len(open_ports)} open ({', '.join(map(str, open_ports[:8])) or 'none'})"
    if tool == "ping":
        return (
            f"Ping {target}: {result.get('avg_ms')} ms avg · "
            f"{result.get('answered')}/{result.get('sent')} · loss {result.get('loss_pct')}%"
        )
    return f"{tool} {target} complete"
