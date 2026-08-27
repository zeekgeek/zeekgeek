"""Scanny-style network tools: DNS, reverse DNS, TCP port scan, ping.

Used by the Trace Radar dashboard alongside traceroute and WHOIS. Live mode
uses the stdlib (:mod:`socket`, :mod:`select`) plus optional system ``ping``.
Demo mode returns canned results so the UI works offline.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import select
import shutil
import socket
import struct
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)

PING_CANDIDATES: tuple[str, ...] = (
    "ping",
    "/sbin/ping",
    "/usr/bin/ping",
    "/usr/sbin/ping",
)


def find_ping_cmd(candidates: Sequence[str] | None = None) -> str | None:
    """Return a ping binary, including macOS /sbin/ping."""
    for name in candidates or PING_CANDIDATES:
        if os.path.sep in name:
            if os.path.isfile(name) and os.access(name, os.X_OK):
                return name
            continue
        path = shutil.which(name)
        if path:
            return path
    return None


def build_ping_command(
    host: str,
    count: int,
    timeout: float,
    *,
    platform: str | None = None,
    ping_bin: str | None = None,
) -> list[str]:
    """Build a ping argv that works on both Linux and macOS Sequoia.

    Linux ``-W`` is seconds per probe. macOS ``-W`` is milliseconds.
    """
    binary = ping_bin or find_ping_cmd() or "ping"
    which = platform if platform is not None else sys.platform
    if which == "darwin":
        wait_ms = max(1, int(timeout * 1000))
        return [binary, "-c", str(count), "-W", str(wait_ms), host]
    timeout_s = max(1, int(timeout))
    return [binary, "-c", str(count), "-W", str(timeout_s), host]

# Common ports Scanny-style tools usually probe first.
COMMON_PORTS = [
    21, 22, 23, 25, 53, 80, 110, 123, 143, 161, 389, 443, 445, 465, 587, 993,
    995, 1433, 1521, 2049, 3306, 3389, 5432, 5900, 6379, 8080, 8443, 27017,
]

DEMO_DNS: dict[str, dict[str, list[str]]] = {
    "one.one.one.one": {
        "A": ["1.1.1.1", "1.0.0.1"],
        "AAAA": ["2606:4700:4700::1111", "2606:4700:4700::1001"],
        "MX": ["1 one.one.one.one"],
        "NS": ["ns1.cloudflare.com", "ns2.cloudflare.com"],
        "TXT": ["v=spf1 -all"],
    },
    "google.com": {
        "A": ["142.250.72.14"],
        "AAAA": ["2607:f8b0:4004:c07::64"],
        "MX": ["10 smtp.google.com"],
        "NS": ["ns1.google.com", "ns2.google.com", "ns3.google.com", "ns4.google.com"],
        "TXT": ["v=spf1 include:_spf.google.com ~all"],
    },
    "cloudflare.com": {
        "A": ["104.16.132.229", "104.16.133.229"],
        "AAAA": ["2606:4700::6810:84e5"],
        "MX": ["36 isaac.ns.cloudflare.com"],
        "NS": ["ns3.cloudflare.com", "ns7.cloudflare.com"],
        "TXT": ["v=spf1 include:_spf.google.com include:spf.protection.outlook.com -all"],
    },
}

DEMO_PTR: dict[str, str] = {
    "1.1.1.1": "one.one.one.one",
    "8.8.8.8": "dns.google",
    "142.250.72.14": "lga25s62-in-f14.1e100.net",
    "104.16.248.249": "one.one.one.one",
}

DEMO_OPEN_PORTS: dict[str, set[int]] = {
    "1.1.1.1": {53, 80, 443, 8080, 8443},
    "8.8.8.8": {53, 443},
    "142.250.72.14": {80, 443},
    "104.16.248.249": {80, 443, 8080, 8443},
    "one.one.one.one": {53, 80, 443, 8080, 8443},
    "google.com": {80, 443},
    "cloudflare.com": {80, 443, 8080, 8443},
}


@dataclass
class DnsResult:
    host: str
    records: dict[str, list[str]] = field(default_factory=dict)
    reverse: str | None = None
    error: str | None = None
    demo: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortResult:
    host: str
    resolved_ip: str | None
    open_ports: list[int] = field(default_factory=list)
    closed_ports: list[int] = field(default_factory=list)
    filtered_ports: list[int] = field(default_factory=list)
    scanned: list[int] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None
    demo: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PingResult:
    host: str
    resolved_ip: str | None
    sent: int
    answered: int
    loss_pct: float
    rtts_ms: list[float] = field(default_factory=list)
    min_ms: float | None = None
    avg_ms: float | None = None
    max_ms: float | None = None
    error: str | None = None
    demo: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def lookup_dns(host: str, *, demo: bool = False) -> DnsResult:
    """Resolve A/AAAA (and reverse PTR when host is an IP)."""
    host = host.strip()
    if not host:
        return DnsResult(host=host, error="Empty host")

    if demo:
        return _demo_dns(host)

    records: dict[str, list[str]] = {}
    reverse: str | None = None
    error: str | None = None

    # Reverse lookup when the query looks like an IP.
    if _looks_like_ip(host):
        try:
            reverse = await asyncio.to_thread(socket.gethostbyaddr, host)
            reverse = reverse[0]
            records["PTR"] = [reverse]
        except OSError as exc:
            error = f"PTR lookup failed: {exc}"
        # Also try AAAA/A as identity.
        records.setdefault("A" if "." in host else "AAAA", [host])
        return DnsResult(host=host, records=records, reverse=reverse, error=error)

    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, None, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        return DnsResult(host=host, error=f"DNS lookup failed: {exc}")

    a_records: list[str] = []
    aaaa_records: list[str] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if family == socket.AF_INET:
            a_records.append(sockaddr[0])
        elif family == socket.AF_INET6:
            aaaa_records.append(sockaddr[0])
    if a_records:
        records["A"] = list(dict.fromkeys(a_records))
    if aaaa_records:
        records["AAAA"] = list(dict.fromkeys(aaaa_records))

    # Best-effort MX via dnspython is intentionally avoided — keep stdlib-only.
    # Try reverse of the first A record for a friendly name.
    if a_records:
        try:
            reverse = (await asyncio.to_thread(socket.gethostbyaddr, a_records[0]))[0]
            records["PTR"] = [reverse]
        except OSError:
            pass

    return DnsResult(host=host, records=records, reverse=reverse)


def _demo_dns(host: str) -> DnsResult:
    if _looks_like_ip(host):
        ptr = DEMO_PTR.get(host, f"host-{host.replace('.', '-')}.example.net")
        return DnsResult(host=host, records={"PTR": [ptr], "A": [host]}, reverse=ptr, demo=True)
    canned = DEMO_DNS.get(host.lower())
    if canned is None:
        # Invent a short A record so the UI always has something to show.
        return DnsResult(
            host=host,
            records={"A": ["203.0.113.10"], "TXT": [f"demo-record-for={host}"]},
            demo=True,
        )
    return DnsResult(host=host, records={k: list(v) for k, v in canned.items()}, demo=True)


async def scan_ports(
    host: str,
    *,
    ports: list[int] | None = None,
    timeout: float = 0.6,
    demo: bool = False,
    concurrency: int = 32,
) -> PortResult:
    """TCP connect-scan a host for open ports (Scanny-style)."""
    host = host.strip()
    ports = list(ports or COMMON_PORTS)
    if not host:
        return PortResult(host=host, resolved_ip=None, error="Empty host", scanned=ports)

    if demo:
        return _demo_port_scan(host, ports)

    try:
        resolved = await asyncio.to_thread(socket.gethostbyname, host)
    except OSError as exc:
        return PortResult(host=host, resolved_ip=None, error=f"DNS failed: {exc}", scanned=ports)

    start = time.perf_counter()
    open_ports: list[int] = []
    closed_ports: list[int] = []
    filtered_ports: list[int] = []
    semaphore = asyncio.Semaphore(concurrency)

    async def _probe(port: int) -> None:
        async with semaphore:
            status = await asyncio.to_thread(_tcp_probe, resolved, port, timeout)
            if status == "open":
                open_ports.append(port)
            elif status == "closed":
                closed_ports.append(port)
            else:
                filtered_ports.append(port)

    await asyncio.gather(*[_probe(port) for port in ports])
    open_ports.sort()
    closed_ports.sort()
    filtered_ports.sort()
    duration_ms = round((time.perf_counter() - start) * 1000.0, 1)
    return PortResult(
        host=host,
        resolved_ip=resolved,
        open_ports=open_ports,
        closed_ports=closed_ports,
        filtered_ports=filtered_ports,
        scanned=ports,
        duration_ms=duration_ms,
    )


def _demo_port_scan(host: str, ports: list[int]) -> PortResult:
    key = host.lower()
    if key in DEMO_OPEN_PORTS:
        open_set = DEMO_OPEN_PORTS[key]
    elif host in DEMO_OPEN_PORTS:
        open_set = DEMO_OPEN_PORTS[host]
    else:
        open_set = {80, 443}
    open_ports = sorted(p for p in ports if p in open_set)
    closed = sorted(p for p in ports if p not in open_set)
    resolved = host if _looks_like_ip(host) else (
        DEMO_DNS.get(key, {}).get("A", ["203.0.113.10"])[0]
    )
    return PortResult(
        host=host,
        resolved_ip=resolved,
        open_ports=open_ports,
        closed_ports=closed[: max(0, len(closed) - 2)],
        filtered_ports=closed[max(0, len(closed) - 2) :],
        scanned=ports,
        duration_ms=42.0,
        demo=True,
    )


def _tcp_probe(ip: str, port: int, timeout: float) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        if result == 0:
            return "open"
        # Common "connection refused" codes → closed; timeout → filtered.
        if result in {111, 61, 10061}:  # Linux/macOS/Windows refuse
            return "closed"
        return "closed"
    except TimeoutError:
        return "filtered"
    except OSError:
        return "filtered"
    finally:
        sock.close()


async def ping_host(
    host: str,
    *,
    count: int = 4,
    timeout: float = 1.0,
    demo: bool = False,
) -> PingResult:
    """ICMP (or UDP fallback) ping for a quick latency sample."""
    host = host.strip()
    if not host:
        return PingResult(host=host, resolved_ip=None, sent=0, answered=0, loss_pct=0.0, error="Empty host")

    if demo:
        return _demo_ping(host, count)

    try:
        resolved = await asyncio.to_thread(socket.gethostbyname, host)
    except OSError as exc:
        return PingResult(
            host=host, resolved_ip=None, sent=0, answered=0, loss_pct=0.0, error=f"DNS failed: {exc}"
        )

    # Prefer system ping when available (needs less privilege than raw ICMP).
    ping_bin = find_ping_cmd()
    if ping_bin:
        try:
            return await asyncio.to_thread(_system_ping, host, resolved, count, timeout, ping_bin)
        except Exception as exc:
            LOGGER.info("system ping failed (%s); trying UDP echo probe", exc)

    rtts: list[float | None] = []
    for index in range(count):
        rtt = await asyncio.to_thread(_udp_echo_probe, resolved, timeout, index)
        rtts.append(rtt)
        await asyncio.sleep(0.05)
    answered = [r for r in rtts if r is not None]
    loss = round(100.0 * (count - len(answered)) / count, 1) if count else 0.0
    return PingResult(
        host=host,
        resolved_ip=resolved,
        sent=count,
        answered=len(answered),
        loss_pct=loss,
        rtts_ms=[round(r, 2) for r in answered],
        min_ms=round(min(answered), 2) if answered else None,
        avg_ms=round(sum(answered) / len(answered), 2) if answered else None,
        max_ms=round(max(answered), 2) if answered else None,
        error=None if answered else "No replies (ICMP may be blocked)",
    )


def _demo_ping(host: str, count: int) -> PingResult:
    random.seed(hash(host) & 0xFFFFFFFF)
    base = 12.0 if "one.one" in host or host.startswith("1.1") else 22.0
    rtts = [round(max(0.4, base + random.uniform(-3, 6)), 2) for _ in range(count)]
    # Drop one probe occasionally for realism.
    if count >= 4 and random.random() < 0.25:
        rtts.pop()
    answered = list(rtts)
    resolved = host if _looks_like_ip(host) else (
        DEMO_DNS.get(host.lower(), {}).get("A", ["203.0.113.10"])[0]
    )
    return PingResult(
        host=host,
        resolved_ip=resolved,
        sent=count,
        answered=len(answered),
        loss_pct=round(100.0 * (count - len(answered)) / count, 1),
        rtts_ms=answered,
        min_ms=min(answered) if answered else None,
        avg_ms=round(sum(answered) / len(answered), 2) if answered else None,
        max_ms=max(answered) if answered else None,
        demo=True,
    )


def _system_ping(
    host: str, resolved: str, count: int, timeout: float, ping_bin: str | None = None
) -> PingResult:
    import re
    import subprocess

    proc = subprocess.run(
        build_ping_command(host, count, timeout, ping_bin=ping_bin),
        capture_output=True,
        text=True,
        timeout=count * (timeout + 1) + 2,
        check=False,
    )
    text = proc.stdout + "\n" + proc.stderr
    rtts = [float(m) for m in re.findall(r"time[=<]([\d.]+)\s*ms", text)]
    # Parse "X packets transmitted, Y received"
    tx = rx = None
    match = re.search(r"(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets\s+)?received", text)
    if match:
        tx, rx = int(match.group(1)), int(match.group(2))
    sent = tx if tx is not None else count
    answered = rx if rx is not None else len(rtts)
    loss = round(100.0 * max(0, sent - answered) / sent, 1) if sent else 0.0
    if not rtts and proc.returncode != 0:
        raise RuntimeError(text.strip() or "ping failed")
    return PingResult(
        host=host,
        resolved_ip=resolved,
        sent=sent,
        answered=answered,
        loss_pct=loss,
        rtts_ms=[round(r, 2) for r in rtts],
        min_ms=round(min(rtts), 2) if rtts else None,
        avg_ms=round(sum(rtts) / len(rtts), 2) if rtts else None,
        max_ms=round(max(rtts), 2) if rtts else None,
    )


def _udp_echo_probe(ip: str, timeout: float, index: int) -> float | None:
    """Best-effort latency probe when ICMP is unavailable (often filtered)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setblocking(False)
        # High port unlikely to be open — we measure ICMP unreachable / timeout.
        port = 33434 + index
        payload = struct.pack("!HH", index, int(time.time() * 1000) & 0xFFFF)
        start = time.perf_counter()
        try:
            sock.sendto(payload, (ip, port))
        except OSError:
            return None
        readable, _, _ = select.select([sock], [], [], timeout)
        if not readable:
            return None
        try:
            sock.recvfrom(512)
        except OSError:
            pass
        return (time.perf_counter() - start) * 1000.0
    finally:
        sock.close()


def _looks_like_ip(value: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET, value)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, value)
        return True
    except OSError:
        return False
