"""Live ICMP probes (TTL-limited ping) used as a traceroute."""

from __future__ import annotations

import asyncio
import platform
import re
import shutil
import socket
import subprocess
import time
from typing import Any

IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
FROM_IP_RE = re.compile(
    r"From\s+(?:(?P<host>[\w.-]+)\s+\()?(?P<ip>\d{1,3}(?:\.\d{1,3}){3})",
    re.IGNORECASE,
)
REPLY_RE = re.compile(
    r"bytes from\s+(?:(?P<host>[\w.-]+)\s+\()?(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\)?"
    r".*time[=<](?P<ms>[\d.]+)\s*ms",
    re.IGNORECASE | re.DOTALL,
)


def resolve_ipv4(host: str) -> list[str]:
    cleaned = (host or "").strip()
    if not cleaned:
        return []
    if IP_RE.match(cleaned):
        return [cleaned]
    try:
        info = socket.getaddrinfo(cleaned, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return []
    return list(dict.fromkeys(item[4][0] for item in info))


def parse_ping_output(text: str) -> dict[str, Any]:
    """Parse iputils/BSD ping stdout into a hop probe."""
    reply = REPLY_RE.search(text)
    if reply:
        return {
            "ip": reply.group("ip"),
            "hostname": reply.group("host") if reply.group("host") and not IP_RE.match(reply.group("host")) else None,
            "rtt_ms": float(reply.group("ms")),
            "reached": True,
            "ttl_exceeded": False,
            "timed_out": False,
        }
    exceeded = "time to live exceeded" in text.lower() or "time-to-live exceeded" in text.lower()
    from_hit = FROM_IP_RE.search(text)
    if exceeded and from_hit:
        ip = from_hit.group("ip")
        host = from_hit.group("host")
        return {
            "ip": ip,
            "hostname": host if host and not IP_RE.match(host) else None,
            "rtt_ms": None,
            "reached": False,
            "ttl_exceeded": True,
            "timed_out": False,
        }
    return {
        "ip": None,
        "hostname": None,
        "rtt_ms": None,
        "reached": False,
        "ttl_exceeded": False,
        "timed_out": True,
    }


def ping_command(target: str, *, ttl: int | None, timeout: float) -> list[str]:
    binary = shutil.which("ping")
    if not binary:
        raise FileNotFoundError("ping is not installed")
    system = platform.system().lower()
    if system == "darwin":
        cmd = [binary, "-c", "1", "-W", str(max(1, int(timeout * 1000)))]
        if ttl is not None:
            cmd.extend(["-m", str(ttl)])
        cmd.append(target)
        return cmd
    cmd = [binary, "-4", "-c", "1", "-W", str(timeout)]
    if ttl is not None:
        cmd.extend(["-t", str(ttl)])
    cmd.append(target)
    return cmd


def ping_once(target: str, *, ttl: int | None = None, timeout: float = 0.45) -> dict[str, Any]:
    """One ICMP echo. With ttl set this is a traceroute probe."""
    cmd = ping_command(target, ttl=ttl, timeout=timeout)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1.5, timeout + 1.0),
        )
    except subprocess.TimeoutExpired:
        return {
            "ip": None,
            "hostname": None,
            "rtt_ms": None,
            "reached": False,
            "ttl_exceeded": False,
            "timed_out": True,
            "elapsed_ms": (time.perf_counter() - started) * 1000,
        }
    elapsed_ms = (time.perf_counter() - started) * 1000
    parsed = parse_ping_output((completed.stdout or "") + (completed.stderr or ""))
    parsed["elapsed_ms"] = elapsed_ms
    timeout_ms = timeout * 1000
    if parsed.get("ttl_exceeded") and parsed.get("ip") and elapsed_ms < timeout_ms * 0.92:
        parsed["rtt_ms"] = round(elapsed_ms, 2)
        parsed["timed_out"] = False
    return parsed


def traceroute_from_probes(
    probes: dict[int, dict[str, Any]],
    dest_ips: set[str],
    max_hops: int,
) -> list[dict[str, Any]]:
    """Build an ordered hop list from TTL → probe results, stopping at the destination."""
    reached_at: int | None = None
    for ttl in range(1, max_hops + 1):
        probe = probes.get(ttl) or {}
        ip = probe.get("ip")
        if probe.get("reached") or (ip and ip in dest_ips):
            reached_at = ttl
            break
    last = reached_at or max_hops
    hops: list[dict[str, Any]] = []
    for ttl in range(1, last + 1):
        probe = probes.get(ttl) or {}
        ip = probe.get("ip")
        rtt = probe.get("rtt_ms")
        reached = bool(probe.get("reached") or (ip and ip in dest_ips))
        timed_out = bool(probe.get("timed_out") if probe else True)
        if reached:
            timed_out = False
        hops.append(
            {
                "hop": ttl,
                "ip": ip,
                "hostname": probe.get("hostname"),
                "rtts": [] if rtt is None else [float(rtt)],
                "timed_out": timed_out or (ip is None and not reached),
                "reached": reached,
            }
        )
    return hops


async def traceroute_ping_async(
    target: str,
    *,
    max_hops: int = 20,
    timeout: float = 0.45,
) -> list[dict[str, Any]]:
    dest_ips = set(await asyncio.to_thread(resolve_ipv4, target))
    if not dest_ips and IP_RE.match(target.strip()):
        dest_ips = {target.strip()}

    async def probe(ttl: int) -> tuple[int, dict[str, Any]]:
        result = await asyncio.to_thread(ping_once, target, ttl=ttl, timeout=timeout)
        if result.get("reached") and result.get("ip"):
            dest_ips.add(result["ip"])
        return ttl, result

    pairs = await asyncio.gather(*[probe(ttl) for ttl in range(1, max_hops + 1)])
    probes = dict(pairs)
    hops = traceroute_from_probes(probes, dest_ips, max_hops)
    if hops and dest_ips and hops[-1].get("ip") in dest_ips:
        hops[-1]["reached"] = True
        hops[-1]["timed_out"] = False
    return hops
