"""In-memory path, hop history, graph, and problem-router state."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .analysis import (
    HopReading,
    classify_hops,
    end_to_end_ms,
    find_problems,
    grade_path,
    summarize,
)
from .providers import enrich_dict, provider_for_asn, provider_for_ip
from .topology import (
    BACKGROUND_TARGETS,
    DEFAULT_TARGET,
    LAN_DEVICES,
    HopTemplate,
    node_id_for,
    resolve_path,
    sample_graph,
    unique_templates,
)

HISTORY = 48
EVENTS = 80


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass
class HopTrack:
    ip: str | None
    hostname: str | None
    template: HopTemplate | None = None
    history: deque[float | None] = field(default_factory=lambda: deque(maxlen=HISTORY))
    asn: str | None = None
    as_name: str | None = None
    provider: str | None = None
    city: str | None = None
    country: str | None = None
    role: str | None = None
    notes: str | None = None
    prefix: str | None = None
    provider_detail: dict[str, Any] | None = None

    def record(self, rtt: float | None, hostname: str | None = None) -> None:
        self.history.append(rtt)
        if hostname:
            self.hostname = hostname

    def apply_lookup(self, lookup: dict[str, Any] | None) -> None:
        if not lookup:
            return
        self.asn = lookup.get("asn") or self.asn
        self.as_name = lookup.get("as_name") or self.as_name
        self.provider = lookup.get("provider") or self.provider
        self.city = lookup.get("city") or self.city
        self.country = lookup.get("country") or self.country
        self.role = lookup.get("role") or self.role
        self.notes = lookup.get("notes") or self.notes
        self.prefix = lookup.get("prefix") or self.prefix
        if lookup.get("provider_detail"):
            self.provider_detail = lookup["provider_detail"]

    def extra(self) -> dict[str, Any]:
        if self.provider_detail or self.asn:
            return {
                "asn": self.asn,
                "provider": self.provider,
                "as_name": self.as_name,
                "provider_detail": self.provider_detail,
            }
        return enrich_dict(self.ip, self.template.asn if self.template else None)

    def snapshot(self) -> dict[str, Any]:
        stats = summarize(list(self.history))
        template = self.template
        extra = self.extra()
        return {
            "ip": self.ip,
            "hostname": self.hostname or (template.hostname if template else None),
            "role": self.role or (template.role if template else None),
            "city": self.city or (template.city if template else None),
            "country": self.country,
            "facility": template.facility if template else None,
            "layer": template.layer if template else None,
            "problem_template": bool(template.problem) if template else False,
            "notes": self.notes or (template.notes if template else None),
            **extra,
            **stats.as_dict(),
            "history": [_round(sample) for sample in self.history],
        }


class PathState:
    def __init__(self, mode: str = "demo") -> None:
        self._lock = asyncio.Lock()
        self.mode = mode if mode in {"demo", "live"} else "demo"
        self.source = self.mode
        self.target = DEFAULT_TARGET
        self.tracing = True
        self.probe_count = 0
        self.updated_at = utc_now()
        self.events: deque[dict[str, Any]] = deque(maxlen=EVENTS)
        self.tracks: dict[str, HopTrack] = {}
        self.paths: dict[str, list[dict[str, Any]]] = {}
        self.lan_devices: list[Any] = []
        self.gateway_ip: str | None = None
        self.local_ips: set[str] = set()
        self._last_health: dict[str, str] = {}
        self._cached_graph: dict[str, Any] = {"nodes": [], "links": []}
        self._cached_hops: list[dict[str, Any]] = []
        self._cached_problems: list[dict[str, Any]] = []
        self._cached_classified: list[Any] = []
        if self.mode == "demo":
            self._bootstrap()

    def _nid(self, ip: str | None, hop: int | None) -> str:
        return node_id_for(
            ip,
            hop,
            gateway_ip=self.gateway_ip,
            local_ips=self.local_ips or None,
            demo_lan=self.mode == "demo",
        )

    def _graph_id(self, ip: str | None, hop: int | None) -> str:
        """Stable map identity. Live hops keep a slot so changing IPs do not spawn nodes."""
        if self.mode == "live":
            if ip and self.local_ips and ip in self.local_ips:
                return "lan:you"
            if ip and self.gateway_ip and ip == self.gateway_ip:
                return "lan:gw"
            return f"slot:{int(hop or 0)}"
        return self._nid(ip, hop)

    def _lan(self):
        if self.mode == "live":
            return self.lan_devices
        return list(LAN_DEVICES)

    def _bootstrap(self) -> None:
        for template in unique_templates().values():
            if not template.ip:
                continue
            self.tracks[template.ip] = HopTrack(
                ip=template.ip,
                hostname=template.hostname,
                template=template,
            )
        graph = sample_graph()
        self._cached_graph = graph
        self._cached_hops: list[dict[str, Any]] = []
        self._cached_problems: list[dict[str, Any]] = []
        self._cached_classified: list[Any] = []
        self._seed_demo()

    def _seed_demo(self) -> None:
        from random import Random

        from .tracer import demo_probe

        probe = demo_probe(active_target=self.target, rng=Random(7), now=8.0)
        by_ip = probe.get("by_ip") or {}
        for ip, sample in by_ip.items():
            track = self.tracks.get(ip)
            if track is None:
                track = HopTrack(ip=ip, hostname=sample.hostname, template=sample.template)
                self.tracks[ip] = track
            track.record(sample.rtt_ms, sample.hostname)
        self.paths = probe.get("paths") or {}
        self.probe_count = 1
        self._recompute_locked()

    async def set_lan(self, devices: list[Any]) -> None:
        async with self._lock:
            self.lan_devices = list(devices)
            self.local_ips = {device.ip for device in devices if getattr(device, "kind", None) == "host"}
            gateway = next((device for device in devices if getattr(device, "kind", None) == "gateway"), None)
            self.gateway_ip = gateway.ip if gateway else None
            self._recompute_locked()

    async def add_system_event(self, kind: str, message: str) -> dict[str, Any]:
        event = {"time": iso_time(utc_now()), "kind": kind, "message": message}
        async with self._lock:
            self.events.appendleft(event)
        return event

    async def set_target(self, target: str) -> dict[str, Any]:
        cleaned = (target or "").strip() or DEFAULT_TARGET
        if self.mode == "demo":
            canonical, _ = resolve_path(cleaned)
        else:
            canonical = cleaned
        async with self._lock:
            self.target = canonical
            event = {
                "time": iso_time(utc_now()),
                "kind": "target",
                "message": f"Tracing {canonical}",
            }
            self.events.appendleft(event)
        return event

    async def ingest_demo(self, probe: dict[str, Any], *, source: str = "demo") -> None:
        async with self._lock:
            self.source = source
            self.probe_count += 1
            self.updated_at = utc_now()
            by_ip = probe.get("by_ip") or {}
            for ip, sample in by_ip.items():
                track = self.tracks.get(ip)
                if track is None:
                    track = HopTrack(ip=ip, hostname=sample.hostname, template=sample.template)
                    self.tracks[ip] = track
                track.record(sample.rtt_ms, sample.hostname)
            self.paths = probe.get("paths") or self.paths
            if probe.get("active"):
                self.target = probe["active"]
            self._recompute_locked()

    async def ingest_live(self, hops: list[dict[str, Any]], *, target: str, source: str = "live") -> None:
        async with self._lock:
            if self.mode == "live" and target != self.target:
                return
            self.source = source
            self.updated_at = utc_now()
            self.probe_count += 1
            path: list[dict[str, Any]] = []
            for hop in hops:
                ip = hop.get("ip")
                rtts = hop.get("rtts") or []
                rtt = rtts[0] if rtts else None
                hostname = hop.get("hostname")
                key = ip or f"hop:{target}:{hop['hop']}"
                track = self.tracks.get(key)
                if track is None:
                    track = HopTrack(ip=ip, hostname=hostname)
                    self.tracks[key] = track
                track.record(rtt, hostname)
                if hop.get("lookup"):
                    track.apply_lookup(hop["lookup"])
                path.append(
                    {
                        "hop": hop["hop"],
                        "ip": ip,
                        "hostname": hostname,
                        "rtt_ms": rtt,
                        "timed_out": hop.get("timed_out", rtt is None),
                        "template": None,
                    }
                )
            self.paths[target] = path
            if self.mode == "live":
                for name in list(self.paths):
                    if name != self.target:
                        del self.paths[name]
            self._recompute_locked()

    def _recompute_locked(self) -> None:
        classified = self._classify_active()
        problems = find_problems(classified)
        self._cached_classified = classified
        self._cached_hops = [self._hop_dict(item) for item in classified]
        self._cached_problems = [item.as_dict() for item in problems]
        self._cached_graph = self._build_graph()
        self._emit_health_events(classified)

    def _classify_active(self):
        path = self.paths.get(self.target) or []
        readings: list[HopReading] = []
        for item in path:
            ip = item.get("ip")
            track = self.tracks.get(ip) if ip else None
            stats = summarize(list(track.history)) if track else None
            rtt = item.get("rtt_ms")
            timed_out = bool(item.get("timed_out") or rtt is None)
            readings.append(
                HopReading(
                    hop=int(item["hop"]),
                    ip=ip,
                    hostname=item.get("hostname"),
                    rtt_ms=None if timed_out else rtt,
                    loss_pct=stats.loss_pct if stats else 0.0,
                    timed_out=timed_out,
                )
            )
        return classify_hops(readings)

    def _hop_dict(self, item) -> dict[str, Any]:
        track = self.tracks.get(item.ip) if item.ip else None
        stats = track.snapshot() if track else summarize([]).as_dict()
        template: HopTemplate | None = track.template if track else None
        extra = track.extra() if track else enrich_dict(item.ip, template.asn if template else None)
        node_id = self._graph_id(item.ip, item.hop)
        return {
            "hop": item.hop,
            "id": node_id,
            "ip": item.ip,
            "hostname": item.hostname or stats.get("hostname"),
            "label": _label(item.hostname or stats.get("hostname"), item.ip, hop=item.hop),
            "rtt_ms": _round(item.rtt_ms),
            "added_ms": _round(item.added_ms),
            "health": item.health,
            "reason": item.reason,
            "filtered": item.filtered,
            "timed_out": item.timed_out,
            "role": (track.role if track and track.role else None)
            or stats.get("role")
            or (template.role if template else None),
            "city": (track.city if track and track.city else None)
            or stats.get("city")
            or (template.city if template else None),
            "country": (track.country if track and track.country else None) or stats.get("country"),
            "facility": stats.get("facility") or (template.facility if template else None),
            "notes": stats.get("notes") or (template.notes if template else None),
            "min_ms": stats.get("min_ms"),
            "avg_ms": stats.get("avg_ms"),
            "max_ms": stats.get("max_ms"),
            "jitter_ms": stats.get("jitter_ms"),
            "loss_pct": stats.get("loss_pct") if stats.get("loss_pct") is not None else item.loss_pct,
            "count": stats.get("count") or 0,
            "timeouts": stats.get("timeouts") or 0,
            "history": stats.get("history") or [],
            "asn": extra.get("asn"),
            "provider": extra.get("provider"),
            "as_name": extra.get("as_name"),
            "provider_detail": extra.get("provider_detail"),
            "layer": template.layer if template else None,
            "problem": item.health in {"slow", "loss", "timeout"},
        }

    def _build_graph(self) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        links: list[dict[str, Any]] = []
        active_ips = {item.get("ip") for item in (self.paths.get(self.target) or []) if item.get("ip")}

        for device in self._lan():
            nodes[device.id] = {
                "id": device.id,
                "label": device.name,
                "ip": device.ip,
                "kind": device.kind,
                "layer": device.layer,
                "vendor": device.vendor,
                "health": "ok",
                "hop": 1 if device.kind == "gateway" else 0,
                "rtt_ms": _current(self.tracks.get(device.ip)),
                "added_ms": None,
                "loss_pct": 0.0,
                "asn": "PRIVATE",
                "provider": "Home network",
                "city": "LAN",
                "active": device.id in {"lan:you", "lan:gw"} or device.ip in active_ips,
                "search": f"{device.name} {device.ip} {device.vendor} {device.kind} lan".lower(),
                "notes": device.notes,
            }
        lan_ids = {device.id for device in self._lan()}
        if "lan:you" in lan_ids and "lan:gw" in lan_ids:
            links.append({"source": "lan:you", "target": "lan:gw", "label": "LAN", "ms": None, "health": "ok", "kind": "lan"})
        for device in self._lan():
            if device.id not in {"lan:you", "lan:gw"} and "lan:gw" in lan_ids:
                links.append(
                    {"source": "lan:gw", "target": device.id, "label": "LAN", "ms": None, "health": "ok", "kind": "lan"}
                )

        graph_paths = self._graph_paths()
        for target, path in graph_paths.items():
            readings: list[HopReading] = []
            for item in path:
                ip = item.get("ip")
                track = self.tracks.get(ip) if ip else None
                stats = summarize(list(track.history)) if track else None
                rtt = item.get("rtt_ms")
                timed_out = bool(item.get("timed_out") or rtt is None)
                readings.append(
                    HopReading(
                        hop=int(item["hop"]),
                        ip=ip,
                        hostname=item.get("hostname"),
                        rtt_ms=None if timed_out else rtt,
                        loss_pct=stats.loss_pct if stats else 0.0,
                        timed_out=timed_out,
                    )
                )
            classified_path = classify_hops(readings)
            previous_id = "lan:gw" if "lan:gw" in nodes else ("lan:you" if "lan:you" in nodes else None)
            is_active = target == self.target
            for item, classified in zip(path, classified_path, strict=False):
                ip = item.get("ip")
                template: HopTemplate | None = item.get("template")
                node_id = self._graph_id(ip, item["hop"])
                if node_id in {"lan:you", "lan:gw"}:
                    previous_id = node_id
                    continue
                track = self.tracks.get(ip) if ip else None
                extra = track.extra() if track else enrich_dict(ip, template.asn if template else None)
                health = classified.health
                rtt = classified.rtt_ms
                added = classified.added_ms
                stats = summarize(list(track.history)) if track else None
                search = " ".join(
                    str(part)
                    for part in (
                        item.get("hostname"),
                        ip,
                        extra.get("asn"),
                        extra.get("provider"),
                        extra.get("as_name"),
                        track.city if track else None,
                        track.country if track else None,
                        track.notes if track else None,
                        template.city if template else None,
                        template.role if template else None,
                        template.facility if template else None,
                        health,
                    )
                    if part
                ).lower()
                payload = {
                    "id": node_id,
                    "label": _label(item.get("hostname"), ip, hop=item["hop"]),
                    "hostname": item.get("hostname"),
                    "ip": ip,
                    "kind": (track.role if track and track.role else None)
                    or (template.role if template else None)
                    or "transit",
                    "layer": int(item["hop"]),
                    "hop": item["hop"],
                    "slot": int(item["hop"]),
                    "row": 0 if is_active else 1,
                    "rtt_ms": _round(rtt),
                    "added_ms": _round(added),
                    "loss_pct": _round(stats.loss_pct, 1) if stats else 0.0,
                    "health": health,
                    "asn": extra.get("asn"),
                    "provider": extra.get("provider"),
                    "as_name": extra.get("as_name"),
                    "city": (track.city if track and track.city else None)
                    or (template.city if template else None),
                    "country": track.country if track else None,
                    "facility": template.facility if template else None,
                    "problem": health in {"slow", "loss", "timeout"},
                    "active": is_active or (ip in active_ips),
                    "search": search,
                    "notes": (track.notes if track else None) or (template.notes if template else None),
                    "reason": classified.reason,
                }
                existing = nodes.get(node_id)
                if existing:
                    existing.update(
                        {
                            "rtt_ms": payload["rtt_ms"],
                            "added_ms": payload["added_ms"],
                            "loss_pct": payload["loss_pct"],
                            "health": payload["health"],
                            "problem": payload["problem"] or existing.get("problem"),
                            "active": payload["active"] or existing.get("active"),
                            "hostname": payload["hostname"] or existing.get("hostname"),
                            "provider": payload["provider"] or existing.get("provider"),
                            "as_name": payload["as_name"] or existing.get("as_name"),
                            "asn": payload["asn"] or existing.get("asn"),
                            "city": payload["city"] or existing.get("city"),
                            "country": payload["country"] or existing.get("country"),
                            "facility": payload["facility"] or existing.get("facility"),
                            "notes": payload["notes"] or existing.get("notes"),
                            "reason": payload["reason"] or existing.get("reason"),
                            "search": f"{existing.get('search', '')} {search}".strip(),
                            "hop": payload["hop"] or existing.get("hop"),
                            "slot": payload.get("slot") or existing.get("slot"),
                            "row": payload.get("row") if payload.get("active") else existing.get("row"),
                        }
                    )
                else:
                    nodes[node_id] = payload
                link_health = health
                if added is not None and added >= 25:
                    link_health = "slow"
                label = (
                    "timeout"
                    if health == "timeout"
                    else (f"+{added:.0f} ms" if added is not None and added >= 1 else (f"{rtt:.1f} ms" if rtt else ""))
                )
                if previous_id and previous_id != node_id:
                    links.append(
                        {
                            "source": previous_id,
                            "target": node_id,
                            "label": label,
                            "ms": _round(added if added is not None else rtt),
                            "health": link_health,
                            "kind": "wan",
                            "active": is_active,
                            "problem": health in {"slow", "loss", "timeout"},
                        }
                    )
                previous_id = node_id

        return {"nodes": list(nodes.values()), "links": _unique_links(links)}

    def _emit_health_events(self, classified) -> None:
        for item in classified:
            key = item.ip or f"hop:{item.hop}"
            previous = self._last_health.get(key)
            self._last_health[key] = item.health
            if previous == item.health or item.health in {"ok", "filtered"}:
                continue
            if previous is None and item.health == "warn":
                continue
            name = item.hostname or item.ip or f"hop {item.hop}"
            self.events.appendleft(
                {
                    "time": iso_time(self.updated_at),
                    "kind": item.health,
                    "hop": item.hop,
                    "ip": item.ip,
                    "message": f"Hop {item.hop} {name}: {item.reason or item.health}",
                }
            )

    def _heatmap(self) -> dict[str, Any]:
        rows = []
        for hop in self._cached_hops:
            history = hop.get("history") or []
            padded = [None] * (HISTORY - len(history)) + list(history)
            rows.append(
                {
                    "hop": hop["hop"],
                    "id": hop["id"],
                    "label": hop["label"],
                    "health": hop["health"],
                    "cells": padded[-HISTORY:],
                }
            )
        return {"columns": HISTORY, "rows": rows}

    def _quality(self) -> dict[str, Any]:
        classified = self._cached_classified
        problems = find_problems(classified) if classified else []
        e2e = end_to_end_ms(classified) if classified else None
        grade = grade_path(classified, problems) if classified else "down"
        dest = next((hop for hop in reversed(self._cached_hops) if hop.get("rtt_ms") is not None), None)
        top = self._cached_problems[0] if self._cached_problems else None
        return {
            "end_to_end_ms": _round(e2e),
            "grade": grade,
            "hop_count": len(self._cached_hops),
            "problem_count": len(self._cached_problems),
            "destination": dest.get("hostname") if dest else None,
            "destination_ip": dest.get("ip") if dest else None,
            "top_problem": top,
        }

    def _problem_provider(self) -> dict[str, Any] | None:
        if not self._cached_problems:
            return None
        top = self._cached_problems[0]
        hop = next((item for item in self._cached_hops if item["hop"] == top["hop"]), None)
        if hop is None:
            return None
        detail = hop.get("provider_detail")
        if detail is None:
            provider = provider_for_ip(hop.get("ip")) or provider_for_asn(hop.get("asn"))
            detail = provider.as_dict() if provider else None
        return {
            **top,
            "node_id": hop.get("id") or top.get("node_id"),
            "label": hop.get("label"),
            "hostname": hop.get("hostname"),
            "city": hop.get("city"),
            "facility": hop.get("facility"),
            "notes": hop.get("notes"),
            "min_ms": hop.get("min_ms"),
            "avg_ms": hop.get("avg_ms"),
            "max_ms": hop.get("max_ms"),
            "jitter_ms": hop.get("jitter_ms"),
            "provider_detail": detail,
        }

    def _graph_paths(self) -> dict[str, list[dict[str, Any]]]:
        if self.mode == "live":
            path = self.paths.get(self.target)
            return {self.target: path} if path else {}
        return self.paths

    async def snapshot(self, *, lite: bool = False) -> dict[str, Any]:
        async with self._lock:
            hops = list(self._cached_hops)
            graph = self._cached_graph
            events = list(self.events)
            heatmap = self._heatmap()
            if lite:
                hops = [_lite_hop(hop) for hop in hops]
                graph = {
                    "nodes": [_lite_node(node) for node in graph.get("nodes") or []],
                    "links": graph.get("links") or [],
                }
                events = events[:8]
            return {
                "updated_at": iso_time(self.updated_at),
                "source": self.source,
                "target": self.target,
                "tracing": self.tracing,
                "probe_count": self.probe_count,
                "background_targets": list(self.paths.keys()) if self.mode == "live" else list(BACKGROUND_TARGETS),
                "mode": self.mode,
                "quality": self._quality(),
                "hops": hops,
                "problems": list(self._cached_problems),
                "problem_router": self._problem_provider(),
                "graph": graph,
                "heatmap": heatmap,
                "lan": [
                    {
                        "id": device.id,
                        "name": device.name,
                        "ip": device.ip,
                        "kind": device.kind,
                        "vendor": device.vendor,
                    }
                    for device in self._lan()
                ],
                "events": events,
            }


def _lite_hop(hop: dict[str, Any]) -> dict[str, Any]:
    slim = dict(hop)
    slim.pop("provider_detail", None)
    history = slim.get("history") or []
    slim["history"] = history[-24:]
    return slim


def _lite_node(node: dict[str, Any]) -> dict[str, Any]:
    return {key: node[key] for key in node if key not in {"provider_detail", "notes"}}


def _current(track: HopTrack | None) -> float | None:
    if track is None or not track.history:
        return None
    for sample in reversed(track.history):
        if sample is not None:
            return _round(sample)
    return None


def _label(hostname: str | None, ip: str | None, hop: int | None = None) -> str:
    if hostname:
        parts = [part for part in hostname.rstrip(".").split(".") if part]
        if not parts:
            text = hostname
        elif len(parts) == 1:
            text = parts[0]
        elif len(set(part.lower() for part in parts)) == 1:
            text = hostname.rstrip(".")
        elif len(parts) == 2:
            text = ".".join(parts)
        else:
            text = parts[0]
        return text[:22] + ("…" if len(text) > 22 else "")
    if ip:
        return ip
    return f"hop {hop}" if hop else "?"


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _unique_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for link in links:
        key = (link["source"], link["target"])
        if key in seen:
            # Prefer the active / problem-styled copy.
            if link.get("active") or link.get("problem"):
                for index, existing in enumerate(unique):
                    if existing["source"] == link["source"] and existing["target"] == link["target"]:
                        unique[index] = link
                        break
            continue
        seen.add(key)
        unique.append(link)
    return unique
