"""Traceroute backends: live system traceroute + scripted demo routes.

Live mode shells out to ``traceroute`` (or ``tracepath``) with multiple
probes per hop so packet-loss percentages are meaningful. Each hop is then
enriched with GeoIP and RDAP/WHOIS ownership data.

Demo mode walks canned multi-hop routes (home → ISP → backbone → CDN) with
jittered RTTs, occasional timeouts, and WHOIS records so the globe animates
without network access.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import select
import shutil
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Protocol

from .geoip import GeoInfo, GeoResolver
from .state import HopObservation, RadarState
from .whois import WhoisResolver

LOGGER = logging.getLogger(__name__)

# traceroute hop lines look like:
#  1  192.168.1.1  1.234 ms  1.100 ms  1.050 ms
#  5  * * *
#  6  edge.example.net (1.2.3.4)  12.3 ms  11.8 ms  12.1 ms
HOP_RE = re.compile(
    r"^\s*(\d+)\s+"
    r"(?:"
    r"(?:\*\s*)+"  # all probes timed out
    r"|"
    r"(?:(?P<host>[^\s()]+)\s+)?"
    r"(?:\((?P<paren_ip>[0-9a-fA-F:.]+)\)\s+)?"
    r"(?P<body>.+)"
    r")"
    r"\s*$"
)
RTT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ms")
IP_TOKEN_RE = re.compile(r"^(?P<ip>(?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F:]+)$")
DEFAULT_PROBES = 5  # enough samples for a meaningful per-cycle loss %


class TracerBackend(Protocol):
    async def run(self) -> None:
        """Run until cancelled."""


@dataclass
class ParsedHop:
    ttl: int
    ip: str | None
    hostname: str | None
    rtts_ms: list[float]
    probes: int


def parse_traceroute_output(text: str, *, probes: int = DEFAULT_PROBES) -> list[ParsedHop]:
    """Parse classic ``traceroute -n`` / hostname-aware traceroute output."""
    hops: list[ParsedHop] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("traceroute"):
            continue
        match = HOP_RE.match(line)
        if not match:
            continue
        ttl = int(match.group(1))
        if match.group("body") is None and "*" in line:
            hops.append(ParsedHop(ttl=ttl, ip=None, hostname=None, rtts_ms=[], probes=probes))
            continue
        body = match.group("body") or ""
        if set(body.replace(" ", "")) == {"*"} or body.strip() == "*" * body.count("*"):
            # Line was "N  * * *"
            if not RTT_RE.search(body) and "*" in body:
                hops.append(ParsedHop(ttl=ttl, ip=None, hostname=None, rtts_ms=[], probes=probes))
                continue

        hostname = match.group("host")
        ip = match.group("paren_ip")
        if hostname and IP_TOKEN_RE.match(hostname) and not ip:
            ip = hostname
            hostname = None
        if hostname == "*":
            hostname = None

        # Some traceroute variants print additional IPs mid-line when load-balancing.
        rtts = [float(value) for value in RTT_RE.findall(body)]
        if ip is None:
            for token in body.split():
                token_match = IP_TOKEN_RE.match(token.strip("()"))
                if token_match:
                    ip = token_match.group("ip")
                    break
        # Count timed-out probes as probes - answered when the line mixes answers and stars.
        star_count = body.count("*")
        answered = len(rtts)
        inferred_probes = max(probes, answered + star_count)
        hops.append(
            ParsedHop(
                ttl=ttl,
                ip=ip,
                hostname=hostname,
                rtts_ms=rtts,
                probes=inferred_probes,
            )
        )
    return hops


def parse_tracepath_output(text: str, *, probes: int = 1) -> list[ParsedHop]:
    """Parse ``tracepath`` output (usually one sample per hop)."""
    hops: list[ParsedHop] = []
    #  1?: [LOCALHOST]                      pmtu 1500
    #  1:  192.168.1.1                                           1.234ms
    #  2:  no reply
    line_re = re.compile(
        r"^\s*(\d+)(?:\?)?:\s+(?:(?P<host>\S+)\s+)?(?:(?P<rtt>\d+(?:\.\d+)?)\s*ms|no reply)",
        re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        if "pmtu" in raw_line.lower() and "localhost" in raw_line.lower():
            continue
        match = line_re.match(raw_line.strip())
        if not match:
            continue
        ttl = int(match.group(1))
        host = match.group("host")
        rtt = match.group("rtt")
        if rtt is None or (host and host.lower() == "no"):
            hops.append(ParsedHop(ttl=ttl, ip=None, hostname=None, rtts_ms=[], probes=probes))
            continue
        ip = host if host and IP_TOKEN_RE.match(host) else None
        hostname = None if ip else host
        hops.append(
            ParsedHop(
                ttl=ttl,
                ip=ip,
                hostname=hostname,
                rtts_ms=[float(rtt)],
                probes=probes,
            )
        )
    return hops


# ---------------------------------------------------------------------------
# Demo canned routes / geo
# ---------------------------------------------------------------------------

DEMO_ORIGIN = GeoInfo(
    ip="203.0.113.50",
    lat=37.77,
    lon=-122.42,
    city="San Francisco",
    country="United States",
    country_code="US",
    isp="Demo Fiber",
    org="Demo Home Network",
    asn="AS64500",
)

# ip -> GeoInfo for demo enrichment
DEMO_GEO: dict[str, GeoInfo] = {
    "192.168.1.1": GeoInfo(ip="192.168.1.1", is_private=True),
    "10.0.0.1": GeoInfo(ip="10.0.0.1", is_private=True),
    "24.7.128.1": GeoInfo(
        ip="24.7.128.1", lat=37.34, lon=-121.89, city="San Jose", country="United States",
        country_code="US", isp="Comcast Cable", org="Comcast Cable Communications", asn="AS7922",
    ),
    "68.86.91.1": GeoInfo(
        ip="68.86.91.1", lat=37.78, lon=-122.42, city="San Francisco", country="United States",
        country_code="US", isp="Comcast Cable", org="Comcast Cable Communications", asn="AS7922",
    ),
    "96.110.40.1": GeoInfo(
        ip="96.110.40.1", lat=39.04, lon=-77.49, city="Ashburn", country="United States",
        country_code="US", isp="Comcast Cable", org="Comcast Cable Communications", asn="AS7922",
    ),
    "68.86.85.142": GeoInfo(
        ip="68.86.85.142", lat=41.88, lon=-87.63, city="Chicago", country="United States",
        country_code="US", isp="Comcast Cable", org="Comcast Cable Communications", asn="AS7922",
    ),
    "4.69.140.94": GeoInfo(
        ip="4.69.140.94", lat=39.04, lon=-77.49, city="Ashburn", country="United States",
        country_code="US", isp="Level 3", org="Level 3 Parent, LLC", asn="AS3356",
    ),
    "4.69.219.94": GeoInfo(
        ip="4.69.219.94", lat=40.71, lon=-74.01, city="New York", country="United States",
        country_code="US", isp="Level 3", org="Level 3 Parent, LLC", asn="AS3356",
    ),
    "4.15.180.50": GeoInfo(
        ip="4.15.180.50", lat=33.75, lon=-84.39, city="Atlanta", country="United States",
        country_code="US", isp="Level 3", org="Level 3 Parent, LLC", asn="AS3356",
    ),
    "104.16.248.249": GeoInfo(
        ip="104.16.248.249", lat=37.77, lon=-122.39, city="San Francisco", country="United States",
        country_code="US", isp="Cloudflare", org="Cloudflare, Inc.", asn="AS13335",
    ),
    "142.250.72.14": GeoInfo(
        ip="142.250.72.14", lat=37.42, lon=-122.08, city="Mountain View", country="United States",
        country_code="US", isp="Google", org="Google LLC", asn="AS15169",
    ),
    "151.101.1.67": GeoInfo(
        ip="151.101.1.67", lat=37.78, lon=-122.41, city="San Francisco", country="United States",
        country_code="US", isp="Fastly", org="Fastly, Inc.", asn="AS54113",
    ),
    "8.8.8.8": GeoInfo(
        ip="8.8.8.8", lat=37.39, lon=-122.08, city="Mountain View", country="United States",
        country_code="US", isp="Google", org="Google LLC", asn="AS15169",
    ),
    "1.1.1.1": GeoInfo(
        ip="1.1.1.1", lat=-33.87, lon=151.21, city="Sydney", country="Australia",
        country_code="AU", isp="Cloudflare", org="Cloudflare, Inc.", asn="AS13335",
    ),
}


@dataclass
class _DemoHopSpec:
    ip: str | None
    hostname: str | None
    base_rtt: float
    loss_chance: float = 0.0  # probability a single probe is lost


@dataclass
class _DemoRouteSpec:
    target: str
    resolved_ip: str
    hops: list[_DemoHopSpec]


DEMO_ROUTES: list[_DemoRouteSpec] = [
    _DemoRouteSpec(
        target="one.one.one.one",
        resolved_ip="1.1.1.1",
        hops=[
            _DemoHopSpec("192.168.1.1", "home-gateway.local", 1.2),
            _DemoHopSpec("24.7.128.1", "c-24-7-128-1.hsd1.ca.comcast.net", 8.5),
            _DemoHopSpec("68.86.91.1", "be-111-rar01.sanjose.ca.sfba.comcast.net", 12.0),
            _DemoHopSpec("96.110.40.1", "be-2111-cr02.ashburn.va.ibone.comcast.net", 68.0, loss_chance=0.05),
            _DemoHopSpec(None, None, 0.0, loss_chance=1.0),  # unresponsive hop
            _DemoHopSpec("4.69.140.94", "ae-3.r25.asbnva02.us.bb.gin.ntt.net", 72.0),
            _DemoHopSpec("104.16.248.249", "one.one.one.one", 14.5),
            _DemoHopSpec("1.1.1.1", "one.one.one.one", 15.0),
        ],
    ),
    _DemoRouteSpec(
        target="google.com",
        resolved_ip="142.250.72.14",
        hops=[
            _DemoHopSpec("192.168.1.1", "home-gateway.local", 1.1),
            _DemoHopSpec("24.7.128.1", "c-24-7-128-1.hsd1.ca.comcast.net", 9.0),
            _DemoHopSpec("68.86.85.142", "be-21-ar01.austtx.tx.ibone.comcast.net", 42.0, loss_chance=0.1),
            _DemoHopSpec("4.69.219.94", "ae-4.r21.nycmny01.us.bb.gin.ntt.net", 78.0),
            _DemoHopSpec("4.15.180.50", "google-level3-peer.atlnga.level3.net", 85.0, loss_chance=0.05),
            _DemoHopSpec("142.250.72.14", "lga25s62-in-f14.1e100.net", 22.0),
        ],
    ),
    _DemoRouteSpec(
        target="fastly.com",
        resolved_ip="151.101.1.67",
        hops=[
            _DemoHopSpec("10.0.0.1", "office-gw.local", 0.8),
            _DemoHopSpec("24.7.128.1", "c-24-7-128-1.hsd1.ca.comcast.net", 7.5),
            _DemoHopSpec("68.86.91.1", "be-111-rar01.sanjose.ca.sfba.comcast.net", 11.0),
            _DemoHopSpec("151.101.1.67", "fastly.map.fastly.net", 13.0),
        ],
    ),
]


def python_udp_traceroute(
    target: str,
    *,
    probes: int = DEFAULT_PROBES,
    max_hops: int = 30,
    timeout: float = 1.2,
) -> list[ParsedHop]:
    """UDP traceroute using ``IP_TTL`` + ``IP_RECVERR`` (Linux).

    Works without the system ``traceroute`` binary. Requires the ability to
    receive ICMP errors on a datagram socket (``IP_RECVERR``). Raises
    ``RuntimeError`` when the platform cannot support this path.
    """
    try:
        dest_ip = socket.gethostbyname(target)
    except OSError as exc:
        raise RuntimeError(f"DNS lookup failed for {target}: {exc}") from exc

    hops: list[ParsedHop] = []
    destination_reached = False

    # Linux defines IP_RECVERR as 11; some Python builds omit the constant.
    recv_err = getattr(socket, "IP_RECVERR", 11)

    for ttl in range(1, max_hops + 1):
        rtts: list[float] = []
        hop_ip: str | None = None
        for probe_index in range(probes):
            ip, rtt = _udp_probe_once(
                dest_ip,
                ttl=ttl,
                probe_index=probe_index,
                timeout=timeout,
                recv_err=recv_err,
            )
            if ip is not None:
                hop_ip = ip
            if rtt is not None:
                rtts.append(rtt)
            if ip == dest_ip:
                destination_reached = True
        hops.append(
            ParsedHop(
                ttl=ttl,
                ip=hop_ip,
                hostname=None,
                rtts_ms=rtts,
                probes=probes,
            )
        )
        if destination_reached:
            break

    if not hops:
        raise RuntimeError("UDP traceroute produced no hops")
    # If every hop timed out, the platform likely cannot surface ICMP errors.
    if all(h.ip is None for h in hops):
        raise RuntimeError("UDP traceroute received no ICMP replies (need CAP_NET_RAW or traceroute)")
    return hops


def _udp_probe_once(
    dest_ip: str,
    *,
    ttl: int,
    probe_index: int,
    timeout: float,
    recv_err: int = 11,
) -> tuple[str | None, float | None]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
        try:
            sock.setsockopt(socket.IPPROTO_IP, recv_err, 1)
        except OSError as exc:
            raise RuntimeError(f"IP_RECVERR unsupported: {exc}") from exc
        sock.setblocking(False)
        port = 33434 + (ttl * 10 + probe_index) % 20000
        payload = f"TR{ttl}-{probe_index}".encode("ascii")
        start = time.perf_counter()
        try:
            sock.sendto(payload, (dest_ip, port))
        except OSError:
            return None, None

        deadline = start + timeout
        while time.perf_counter() < deadline:
            remaining = max(0.0, deadline - time.perf_counter())
            # On Linux, ICMP errors surface as exceptional conditions (POLLERR).
            readable, _, errored = select.select([sock], [], [sock], remaining)
            if not readable and not errored:
                break
            try:
                errqueue = getattr(socket, "MSG_ERRQUEUE", 0x2000)
                _data, ancdata, _flags, addr = sock.recvmsg(512, 512, errqueue)
                hop_ip = _parse_recverr_ip(ancdata, recv_err=recv_err) or (addr[0] if addr else None)
                rtt = (time.perf_counter() - start) * 1000.0
                return hop_ip, rtt
            except BlockingIOError:
                continue
            except OSError:
                try:
                    _data, addr = sock.recvfrom(512)
                    rtt = (time.perf_counter() - start) * 1000.0
                    return addr[0] if addr else None, rtt
                except OSError:
                    break
        return None, None
    finally:
        sock.close()


def _parse_recverr_ip(ancdata: list, *, recv_err: int = 11) -> str | None:
    for level, typ, data in ancdata:
        if level != getattr(socket, "SOL_IP", 0):
            continue
        if typ != recv_err or len(data) < 20:
            continue
        # sock_extended_err is 16 bytes; sockaddr_in follows.
        try:
            family = struct.unpack_from("@H", data, 16)[0]
            if family == socket.AF_INET and len(data) >= 24:
                return socket.inet_ntoa(data[20:24])
        except (struct.error, OSError, ValueError):
            pass
        if len(data) >= 4:
            try:
                return socket.inet_ntoa(data[-4:])
            except OSError:
                pass
    return None


@dataclass
class LiveTracerBackend:
    """Run system traceroute against configured targets on an interval."""

    state: RadarState
    targets: list[str]
    interval: float = 45.0
    probes: int = DEFAULT_PROBES
    max_hops: int = 30
    geo: GeoResolver = field(default_factory=GeoResolver)
    whois: WhoisResolver = field(default_factory=WhoisResolver)

    async def run(self) -> None:
        for target in self.targets:
            await self.state.request_trace(target)
        origin = await self.geo.lookup_self()
        await self.state.set_origin(origin)

        mode = "system"
        if self._find_traceroute_cmd() or shutil.which("tracepath"):
            await self.state.add_system_event("tracer-live", "Live traceroute backend started (system binary)")
        else:
            # Prove the Python UDP path works before committing to the live loop.
            try:
                await asyncio.to_thread(python_udp_traceroute, "1.1.1.1", probes=1, max_hops=3, timeout=1.0)
                mode = "python-udp"
                await self.state.add_system_event(
                    "tracer-live",
                    "Live traceroute backend started (Python UDP — no system traceroute binary)",
                )
            except Exception as exc:
                raise RuntimeError(
                    f"No traceroute/tracepath binary and Python UDP probe failed ({exc})"
                ) from exc

        self._mode = mode
        while True:
            new_target = await self.state.next_new_target(timeout=0.1)
            if new_target:
                await self._trace_one(new_target)
            for target in await self.state.known_targets():
                await self._trace_one(target)
            # Wait for interval, but wake early if the UI requests a new target.
            waited = 0.0
            while waited < self.interval:
                target = await self.state.next_new_target(timeout=1.0)
                waited += 1.0
                if target:
                    await self._trace_one(target)
                    break

    async def _trace_one(self, target: str) -> None:
        try:
            resolved = await asyncio.to_thread(socket.gethostbyname, target)
        except OSError:
            resolved = None
        try:
            hops = await self._run_traceroute(target)
        except Exception as exc:
            await self.state.ingest_trace(
                target, resolved_ip=resolved, hops=[], destination_reached=False, error=str(exc)
            )
            return
        observations = await self._enrich(hops)
        destination_reached = bool(
            resolved and observations and observations[-1].ip == resolved
        ) or bool(observations and observations[-1].ip is not None and observations[-1].ttl >= len(observations))
        # Prefer exact IP match when available.
        if resolved:
            destination_reached = any(obs.ip == resolved for obs in observations)
        await self.state.ingest_trace(
            target,
            resolved_ip=resolved,
            hops=observations,
            destination_reached=destination_reached,
        )

    async def _enrich(self, hops: list[ParsedHop]) -> list[HopObservation]:
        ips = [hop.ip for hop in hops if hop.ip]
        geo_map = await self.geo.lookup_many(ips)
        whois_map = await self.whois.lookup_many(ips)
        observations: list[HopObservation] = []
        for hop in hops:
            geo = geo_map.get(hop.ip) if hop.ip else None
            whois = whois_map.get(hop.ip) if hop.ip else None
            observations.append(
                HopObservation(
                    ttl=hop.ttl,
                    ip=hop.ip,
                    rtts_ms=list(hop.rtts_ms),
                    probes=hop.probes,
                    hostname=hop.hostname,
                    geo=geo,
                    whois=whois,
                )
            )
        return observations

    async def _run_traceroute(self, target: str) -> list[ParsedHop]:
        cmd = self._find_traceroute_cmd()
        if cmd:
            args = [cmd, "-n", "-q", str(self.probes), "-m", str(self.max_hops), "-w", "2", target]
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            text = stdout.decode("utf-8", errors="replace")
            if proc.returncode not in (0, 1) and not text.strip():
                raise RuntimeError(stderr.decode("utf-8", errors="replace") or f"{cmd} failed")
            hops = parse_traceroute_output(text, probes=self.probes)
            if hops:
                return hops
        if shutil.which("tracepath"):
            proc = await asyncio.create_subprocess_exec(
                "tracepath",
                "-n",
                target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            text = stdout.decode("utf-8", errors="replace")
            hops = parse_tracepath_output(text, probes=1)
            if hops:
                return hops
            raise RuntimeError(stderr.decode("utf-8", errors="replace") or "tracepath produced no hops")

        # No system binary — use the pure-Python UDP / IP_RECVERR path.
        return await asyncio.to_thread(
            python_udp_traceroute,
            target,
            probes=self.probes,
            max_hops=self.max_hops,
            timeout=1.2,
        )

    def _find_traceroute_cmd(self) -> str | None:
        for name in ("traceroute", "traceroute6"):
            path = shutil.which(name)
            if path:
                return path
        return None


@dataclass
class DemoTracerBackend:
    """Scripted multi-hop routes with jitter, packet loss, geo, and WHOIS."""

    state: RadarState
    targets: list[str] = field(default_factory=list)
    interval: float = 3.0
    probes: int = DEFAULT_PROBES
    whois: WhoisResolver = field(default_factory=lambda: WhoisResolver(demo=True))

    def __post_init__(self) -> None:
        random.seed(20260731)
        self._specs = {route.target: route for route in DEMO_ROUTES}
        # Allow CLI targets that match canned demos; invent a short route otherwise.
        for target in self.targets:
            if target not in self._specs:
                self._specs[target] = _DemoRouteSpec(
                    target=target,
                    resolved_ip="8.8.8.8",
                    hops=[
                        _DemoHopSpec("192.168.1.1", "home-gateway.local", 1.0),
                        _DemoHopSpec("24.7.128.1", "isp-edge.example.net", 10.0, loss_chance=0.1),
                        _DemoHopSpec("4.69.140.94", "backbone.example.net", 40.0),
                        _DemoHopSpec("8.8.8.8", target, 18.0),
                    ],
                )

    async def run(self) -> None:
        await self.state.set_origin(DEMO_ORIGIN)
        await self.state.add_system_event(
            "tracer-demo",
            "Demo traceroute: multi-hop routes with packet-loss % and WHOIS ownership data",
        )
        seed_targets = self.targets or [route.target for route in DEMO_ROUTES]
        for target in seed_targets:
            await self.state.request_trace(target)

        while True:
            new_target = await self.state.next_new_target(timeout=0.05)
            if new_target and new_target not in self._specs:
                self._specs[new_target] = _DemoRouteSpec(
                    target=new_target,
                    resolved_ip="8.8.8.8",
                    hops=[
                        _DemoHopSpec("192.168.1.1", "home-gateway.local", 1.0),
                        _DemoHopSpec("24.7.128.1", "isp-edge.example.net", 12.0, loss_chance=0.15),
                        _DemoHopSpec("8.8.8.8", new_target, 20.0),
                    ],
                )
            for target in await self.state.known_targets():
                await self._emit_trace(target)
            # Sleep, but wake for UI-requested targets.
            waited = 0.0
            while waited < self.interval:
                target = await self.state.next_new_target(timeout=0.5)
                waited += 0.5
                if target:
                    if target not in self._specs:
                        self._specs[target] = _DemoRouteSpec(
                            target=target,
                            resolved_ip="1.1.1.1",
                            hops=[
                                _DemoHopSpec("192.168.1.1", "home-gateway.local", 1.0),
                                _DemoHopSpec("104.16.248.249", "cdn-edge.example.net", 16.0),
                                _DemoHopSpec("1.1.1.1", target, 16.5),
                            ],
                        )
                    await self._emit_trace(target)
                    break

    async def _emit_trace(self, target: str) -> None:
        spec = self._specs.get(target)
        if spec is None:
            return
        whois_map = await self.whois.lookup_many([h.ip for h in spec.hops if h.ip])
        observations: list[HopObservation] = []
        for index, hop_spec in enumerate(spec.hops, start=1):
            rtts: list[float] = []
            if hop_spec.ip is not None:
                for _ in range(self.probes):
                    if random.random() < hop_spec.loss_chance:
                        continue
                    jitter = random.uniform(-0.15, 0.25) * max(hop_spec.base_rtt, 1.0)
                    rtts.append(round(max(0.2, hop_spec.base_rtt + jitter), 2))
            geo = DEMO_GEO.get(hop_spec.ip) if hop_spec.ip else None
            whois = whois_map.get(hop_spec.ip) if hop_spec.ip else None
            observations.append(
                HopObservation(
                    ttl=index,
                    ip=hop_spec.ip if rtts or hop_spec.loss_chance < 1.0 else hop_spec.ip,
                    rtts_ms=rtts,
                    probes=self.probes if hop_spec.ip is not None else self.probes,
                    hostname=hop_spec.hostname if hop_spec.ip else None,
                    geo=geo,
                    whois=whois,
                )
            )
            # Fully unresponsive hop (loss_chance == 1): keep IP None like real traceroute.
            if hop_spec.ip is None:
                observations[-1] = HopObservation(
                    ttl=index, ip=None, rtts_ms=[], probes=self.probes, hostname=None
                )
        await self.state.ingest_trace(
            target,
            resolved_ip=spec.resolved_ip,
            hops=observations,
            destination_reached=True,
        )
