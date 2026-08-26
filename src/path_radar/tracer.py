"""Demo probe engine and live traceroute parser / runner."""

from __future__ import annotations

import math
import os
import random
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from .topology import BACKGROUND_TARGETS, HopTemplate, unique_templates, resolve_path

IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


@dataclass
class ProbeSample:
    ip: str | None
    hostname: str | None
    rtt_ms: float | None
    template: HopTemplate | None = None


def sample_rtt(template: HopTemplate, rng: random.Random, now: float | None = None) -> float | None:
    """Draw one probe RTT for a hop, with optional evening congestion on problem hops."""
    if rng.random() < template.loss:
        return None
    base = template.base_rtt
    if template.problem:
        clock = now if now is not None else time.monotonic()
        # Slow sine so the heatmap breathes, plus rare spikes.
        base += 22.0 * (0.5 + 0.5 * math.sin(clock / 14.0))
        if rng.random() < 0.08:
            base += rng.uniform(40.0, 90.0)
    value = rng.gauss(base, template.jitter)
    return max(0.12, value)


def demo_probe(
    *,
    active_target: str,
    rng: random.Random,
    now: float | None = None,
) -> dict[str, Any]:
    """Sample every unique hop IP once, then assemble every demo path from those RTTs."""
    clock = now if now is not None else time.monotonic()
    templates = unique_templates()
    by_ip: dict[str, ProbeSample] = {}
    for ip, template in templates.items():
        rtt = sample_rtt(template, rng, clock)
        by_ip[ip] = ProbeSample(ip=ip, hostname=template.hostname, rtt_ms=rtt, template=template)

    paths: dict[str, list[dict[str, Any]]] = {}
    targets = list(BACKGROUND_TARGETS)
    canonical, _ = resolve_path(active_target)
    if canonical not in targets:
        targets.append(canonical)

    for target in targets:
        _name, hops = resolve_path(target)
        path: list[dict[str, Any]] = []
        for hop in hops:
            sample = by_ip.get(hop.ip or "")
            rtt = sample.rtt_ms if sample else sample_rtt(hop, rng, clock)
            path.append(
                {
                    "hop": hop.hop,
                    "ip": hop.ip,
                    "hostname": hop.hostname,
                    "rtt_ms": rtt,
                    "timed_out": rtt is None,
                    "template": hop,
                }
            )
        paths[_name] = path
    return {"by_ip": by_ip, "paths": paths, "active": canonical}


def parse_traceroute(text: str) -> list[dict[str, Any]]:
    """Parse `traceroute` / `traceroute -n` output into hop dicts."""
    hops: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("traceroute"):
            continue
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        hop_n = int(parts[0])
        rest = parts[1:]
        if not rest or all(token == "*" for token in rest):
            hops.append({"hop": hop_n, "ip": None, "hostname": None, "rtts": [], "timed_out": True})
            continue
        hostname: str | None = None
        ip: str | None = None
        rtts: list[float] = []
        index = 0
        while index < len(rest):
            token = rest[index]
            if token in {"*", "ms"}:
                index += 1
                continue
            if token.startswith("(") and token.endswith(")"):
                ip = token[1:-1]
                index += 1
                continue
            try:
                rtts.append(float(token))
                index += 1
                continue
            except ValueError:
                pass
            if IP_RE.match(token):
                ip = token
            else:
                hostname = token
            index += 1
        hops.append(
            {
                "hop": hop_n,
                "ip": ip,
                "hostname": hostname if hostname != ip else None,
                "rtts": rtts,
                "timed_out": not rtts,
            }
        )
    return hops


def run_traceroute(target: str, max_hops: int = 30, wait: float = 1.0) -> list[dict[str, Any]]:
    """Run system traceroute (one probe per hop). Raises if the binary is missing."""
    binary = shutil.which("traceroute") or shutil.which("tracepath")
    if not binary:
        raise FileNotFoundError("traceroute/tracepath is not installed")
    name = os.path.basename(binary)
    if name == "tracepath":
        command = [binary, "-n", "-m", str(max_hops), target]
    else:
        command = [binary, "-n", "-w", str(wait), "-q", "1", "-m", str(max_hops), target]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=max(12.0, max_hops * (wait + 0.4)),
    )
    text = completed.stdout or completed.stderr
    if not text.strip():
        raise RuntimeError(f"{name} produced no output (exit {completed.returncode})")
    hops = parse_traceroute(text)
    if not hops and name == "tracepath":
        hops = _parse_tracepath(text)
    if not hops:
        raise RuntimeError(f"Could not parse {name} output")
    return hops


def reverse_name(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        socket.setdefaulttimeout(0.8)
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname
    except OSError:
        return None


def _parse_tracepath(text: str) -> list[dict[str, Any]]:
    hops: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        match = re.match(r"^(\d+):\s+(\S+)(?:\s+\((\d+\.\d+\.\d+\.\d+)\))?\s*(?:(\d+\.\d+)\s*ms)?", line)
        if not match:
            continue
        hop_n = int(match.group(1))
        host = match.group(2)
        ip = match.group(3)
        rtt = float(match.group(4)) if match.group(4) else None
        if host == "???":
            hops.append({"hop": hop_n, "ip": None, "hostname": None, "rtts": [], "timed_out": True})
            continue
        if IP_RE.match(host):
            ip = ip or host
            host = None
        hops.append(
            {
                "hop": hop_n,
                "ip": ip,
                "hostname": host,
                "rtts": [] if rtt is None else [rtt],
                "timed_out": rtt is None,
            }
        )
    return hops


class DemoTraceBackend:
    def __init__(self, state, interval: float = 1.0, seed: int = 7) -> None:
        self.state = state
        self.interval = interval
        self.rng = random.Random(seed)

    async def run(self) -> None:
        import asyncio

        while True:
            probe = demo_probe(active_target=self.state.target, rng=self.rng)
            await self.state.ingest_demo(probe, source="demo")
            await asyncio.sleep(max(0.2, self.interval))


class LiveTraceBackend:
    def __init__(self, state, interval: float = 3.0) -> None:
        self.state = state
        self.interval = interval

    async def run(self) -> None:
        import asyncio

        while True:
            target = self.state.target
            hops = await asyncio.to_thread(run_traceroute, target)
            for hop in hops:
                if hop.get("ip") and not hop.get("hostname"):
                    hop["hostname"] = await asyncio.to_thread(reverse_name, hop["ip"])
            await self.state.ingest_live(hops, target=target, source="live")
            await asyncio.sleep(max(1.0, self.interval))

