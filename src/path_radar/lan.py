"""Live LAN inventory from the routing table, local addresses, and ARP."""

from __future__ import annotations

import os
import re
import socket
from pathlib import Path

from .topology import LanDevice

IP_RE = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")


def _hex_ipv4(value: str) -> str | None:
    raw = value.strip()
    if len(raw) != 8:
        return None
    try:
        number = int(raw, 16)
    except ValueError:
        return None
    return ".".join(str((number >> shift) & 0xFF) for shift in (0, 8, 16, 24))


def default_gateway() -> str | None:
    route = Path("/proc/net/route")
    if route.exists():
        for line in route.read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            destination, gateway, flags = parts[1], parts[2], parts[3]
            try:
                flag_bits = int(flags, 16)
            except ValueError:
                continue
            if destination == "00000000" and flag_bits & 0x2:
                return _hex_ipv4(gateway)
    return None


def local_ipv4() -> str | None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("1.1.1.1", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        for addr in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not addr.startswith("127."):
                return addr
    except OSError:
        pass
    return None


def arp_neighbors(limit: int = 12) -> list[tuple[str, str]]:
    path = Path("/proc/net/arp")
    if not path.exists():
        return []
    found: list[tuple[str, str]] = []
    for line in path.read_text().splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        ip, flags, mac = parts[0], parts[2], parts[3]
        if not IP_RE.match(ip) or mac == "00:00:00:00:00:00":
            continue
        try:
            if int(flags, 16) & 0x2 == 0:
                continue
        except ValueError:
            continue
        found.append((ip, mac))
        if len(found) >= limit:
            break
    return found


def discover_lan() -> list[LanDevice]:
    host_ip = local_ipv4() or "127.0.0.1"
    gateway = default_gateway()
    host_name = os.uname().nodename if hasattr(os, "uname") else "this-host"
    devices = [
        LanDevice(
            "lan:you",
            host_name or "This host",
            host_ip,
            "host",
            "local",
            layer=0,
            notes="Trace source (this machine).",
        )
    ]
    if gateway:
        devices.append(
            LanDevice(
                "lan:gw",
                "Default gateway",
                gateway,
                "gateway",
                "router",
                layer=1,
                notes="From the kernel routing table.",
            )
        )
    seen = {host_ip, gateway}
    for ip, mac in arp_neighbors():
        if ip in seen:
            continue
        seen.add(ip)
        devices.append(
            LanDevice(
                f"lan:{ip}",
                ip,
                ip,
                "device",
                mac,
                layer=0,
                notes=f"ARP neighbor {mac}",
            )
        )
    return devices
