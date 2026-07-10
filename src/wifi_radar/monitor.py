"""Monitor-mode helpers for Linux WiFi interfaces."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

CommandRunner = Callable[[list[str]], Awaitable[str]]


@dataclass(frozen=True)
class InterfaceInfo:
    name: str
    if_type: str


@dataclass(frozen=True)
class MonitorActivation:
    base_interface: str
    monitor_interface: str
    created_virtual_interface: bool
    note: str


def parse_iw_dev_interfaces(output: str) -> list[InterfaceInfo]:
    interfaces: list[InterfaceInfo] = []
    current_name: str | None = None
    current_type: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("Interface "):
            if current_name is not None and current_type is not None:
                interfaces.append(InterfaceInfo(name=current_name, if_type=current_type))
            current_name = line.split(maxsplit=1)[1]
            current_type = None
        elif line.startswith("type "):
            current_type = line.split(maxsplit=1)[1]
    if current_name is not None and current_type is not None:
        interfaces.append(InterfaceInfo(name=current_name, if_type=current_type))
    return interfaces


class MonitorModeController:
    """Enable and restore monitor mode.

    Preferred approach:
    1) keep base interface managed
    2) create a dedicated virtual monitor interface (e.g. wlan0mon)
    """

    def __init__(self, run_command: CommandRunner) -> None:
        self._run_command = run_command

    async def detect_base_interface(self, preferred: str | None) -> str | None:
        interfaces = await self._interfaces()
        if preferred:
            if any(item.name == preferred for item in interfaces):
                return preferred
            return None
        for item in interfaces:
            if item.if_type != "monitor":
                return item.name
        if interfaces:
            return interfaces[0].name
        return None

    async def enable(self, base_interface: str, preferred_monitor_interface: str | None = None) -> MonitorActivation:
        interfaces = await self._interfaces()
        existing_monitor = next((item.name for item in interfaces if item.if_type == "monitor"), None)
        if existing_monitor is not None:
            return MonitorActivation(
                base_interface=base_interface,
                monitor_interface=existing_monitor,
                created_virtual_interface=False,
                note=f"Using existing monitor interface {existing_monitor}.",
            )

        monitor_interface = preferred_monitor_interface or f"{base_interface}mon"
        try:
            await self._run_command(
                ["iw", "dev", base_interface, "interface", "add", monitor_interface, "type", "monitor"]
            )
            await self._run_command(["ip", "link", "set", monitor_interface, "up"])
            return MonitorActivation(
                base_interface=base_interface,
                monitor_interface=monitor_interface,
                created_virtual_interface=True,
                note=f"Created virtual monitor interface {monitor_interface}.",
            )
        except RuntimeError:
            # Fallback: convert base interface itself to monitor mode.
            await self._run_command(["ip", "link", "set", base_interface, "down"])
            await self._run_command(["iw", "dev", base_interface, "set", "type", "monitor"])
            await self._run_command(["ip", "link", "set", base_interface, "up"])
            return MonitorActivation(
                base_interface=base_interface,
                monitor_interface=base_interface,
                created_virtual_interface=False,
                note=f"Converted {base_interface} into monitor mode.",
            )

    async def restore(self, activation: MonitorActivation) -> None:
        if activation.created_virtual_interface:
            await self._run_command(["ip", "link", "set", activation.monitor_interface, "down"])
            await self._run_command(["iw", "dev", activation.monitor_interface, "del"])
            return
        # Converted base interface: put it back in managed mode.
        await self._run_command(["ip", "link", "set", activation.base_interface, "down"])
        await self._run_command(["iw", "dev", activation.base_interface, "set", "type", "managed"])
        await self._run_command(["ip", "link", "set", activation.base_interface, "up"])

    async def _interfaces(self) -> list[InterfaceInfo]:
        output = await self._run_command(["iw", "dev"])
        return parse_iw_dev_interfaces(output)


async def run_command(command: list[str]) -> str:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace").strip() or f"{command[0]} exited {process.returncode}")
    return stdout.decode(errors="replace")
