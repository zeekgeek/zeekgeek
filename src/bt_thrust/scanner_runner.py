"""Background BLE scanner lifecycle with restart support."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field

from .bluetooth_probe import probe_adapter
from .demo_scanner import DemoScannerBackend
from .scanner import BleakScannerBackend
from .state import ControllerState

LOGGER = logging.getLogger(__name__)


@dataclass
class ScannerRunner:
    state: ControllerState
    force_demo: bool = False
    _task: asyncio.Task | None = field(default=None, init=False)
    _prefer_demo: bool = False
    _last_probe: dict | None = field(default=None, init=False)

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self._run_loop(), name="scanner-runner")
        return self._task

    async def diagnostics(self) -> dict:
        probe = await probe_adapter()
        self._last_probe = probe.to_dict()
        await self.state.set_adapter_probe(self._last_probe)
        snapshot = await self.state.snapshot()
        return {
            "probe": self._last_probe,
            "scanner": snapshot["scanner"],
            "data_source": snapshot["scanner"].get("mode", "off"),
            "live_required": not self.force_demo,
        }

    async def restart(self, *, demo: bool = False) -> dict:
        self._prefer_demo = demo or self.force_demo
        await self.state.set_scanner_paused(False)

        if self._prefer_demo:
            await self._start_demo("Demo scan. Simulated devices — not from a live adapter.")
            return await self.diagnostics()

        probe = await probe_adapter()
        self._last_probe = probe.to_dict()
        await self.state.set_adapter_probe(self._last_probe)
        if not probe.available:
            message = (
                f"No live Bluetooth adapter ({probe.error}). "
                "Connect a powered BLE adapter and ensure bluetoothd is running."
            )
            await self.state.set_scanner_active(False, error=message, mode="off")
            await self.state.add_system_event("scanner-error", message)
            return await self.diagnostics()

        await self.state.set_scanner_active(True, error=None, mode="live")
        await self.state.add_system_event(
            "scanner-live",
            f"Live BLE adapter verified ({probe.device_count} device(s) seen during probe).",
        )
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = asyncio.create_task(self._run_loop(), name="scanner-runner")
        return await self.diagnostics()

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._run_once()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("Scanner runner stopped: %s", exc)
                await self.state.set_scanner_active(False, error=str(exc), mode="off")
                return

    async def _run_once(self) -> None:
        await self.state.set_scanner_paused(False)

        if self._prefer_demo or self.force_demo:
            await self._start_demo("Demo scanner active. Not reading a live adapter.")
            return

        probe = await probe_adapter()
        self._last_probe = probe.to_dict()
        await self.state.set_adapter_probe(self._last_probe)
        if not probe.available:
            message = f"Live Bluetooth adapter lost ({probe.error})."
            await self.state.set_scanner_active(False, error=message, mode="off")
            await self.state.add_system_event("scanner-error", message)
            raise RuntimeError(message)

        await self.state.set_scanner_active(True, error=None, mode="live")
        await BleakScannerBackend(self.state).run()

    async def _start_demo(self, message: str) -> None:
        LOGGER.info(message)
        await self.state.set_scanner_active(True, error=None, mode="demo")
        await self.state.add_system_event("scanner-demo", message)
        self._prefer_demo = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = asyncio.create_task(self._run_demo_loop(message), name="scanner-runner")

    async def _run_demo_loop(self, message: str) -> None:
        try:
            await DemoScannerBackend(self.state).run()
        except asyncio.CancelledError:
            raise
