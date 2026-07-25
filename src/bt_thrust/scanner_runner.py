"""Background BLE scanner lifecycle with restart support."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from dataclasses import dataclass, field

from .demo_scanner import DemoScannerBackend
from .scanner import BleakScannerBackend
from .state import ControllerState

LOGGER = logging.getLogger(__name__)


def _cloud_environment() -> bool:
    return os.environ.get("CURSOR_AGENT") == "1"


@dataclass
class ScannerRunner:
    state: ControllerState
    force_demo: bool = False
    _task: asyncio.Task | None = field(default=None, init=False)
    _prefer_demo: bool = False

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self._run_loop(), name="scanner-runner")
        return self._task

    async def restart(self, *, demo: bool = False) -> None:
        use_demo = demo or self.force_demo or _cloud_environment()
        self._prefer_demo = use_demo
        await self.state.set_scanner_paused(False)
        await self.state.set_scanner_active(True, error=None, mode="live" if not use_demo else "demo")
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = asyncio.create_task(self._run_loop(), name="scanner-runner")

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

        if self._prefer_demo or self.force_demo or _cloud_environment():
            await self._run_demo(
                "Simulated scan active — showing 10 nearby devices (≥ -85 dBm)."
                if _cloud_environment() and not self.force_demo
                else "Demo scanner started from Scan ON."
            )
            return

        await self.state.set_scanner_active(True, error=None, mode="live")
        try:
            await BleakScannerBackend(self.state).run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = (
                f"Live scanner unavailable ({type(exc).__name__}: {exc}). "
                "Click Scan ON to retry, or run with --demo."
            )
            LOGGER.warning(message)
            await self.state.set_scanner_active(False, error=str(exc), mode="off")
            await self.state.add_system_event("scanner-error", message)
            raise

    async def _run_demo(self, message: str) -> None:
        LOGGER.info(message)
        await self.state.set_scanner_active(True, error=None, mode="demo")
        await self.state.add_system_event("scanner-demo", message)
        self._prefer_demo = False
        await DemoScannerBackend(self.state).run()
