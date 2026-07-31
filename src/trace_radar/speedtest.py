"""Speedtest-style connection quality measurements.

Latency/jitter/loss come from repeated TCP connect probes (no raw sockets
needed). Throughput uses Cloudflare's public speed endpoints
(``speed.cloudflare.com/__down`` and ``__up``). Demo mode simulates a
realistic run so the dashboard gauges animate without network access.

Live failures (blocked User-Agent, egress limits, etc.) auto-fall back to the
demo run so the UI always completes a usable measurement.
"""

from __future__ import annotations

import asyncio
import logging
import random
import socket
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .state import RadarState

LOGGER = logging.getLogger(__name__)

DOWNLOAD_URL = "https://speed.cloudflare.com/__down?bytes={size}"
UPLOAD_URL = "https://speed.cloudflare.com/__up"
# Smaller payloads keep the UI responsive while still producing a real Mbps reading.
DOWNLOAD_BYTES = 10_000_000
UPLOAD_BYTES = 2_000_000
LATENCY_HOST = "1.1.1.1"
LATENCY_PORT = 443
LATENCY_PROBES = 10
MAX_PHASE_SECONDS = 12.0

# Cloudflare returns 403 for non-browser User-Agents from some networks.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def compute_jitter(rtts: list[float]) -> float:
    """Mean absolute difference between successive RTT samples (ms)."""
    if len(rtts) < 2:
        return 0.0
    deltas = [abs(b - a) for a, b in zip(rtts, rtts[1:])]
    return sum(deltas) / len(deltas)


def summarize_rtts(samples: list[float | None]) -> dict[str, float | None]:
    """Min/avg/max/jitter/loss summary for probe samples (``None`` = lost)."""
    answered = [s for s in samples if s is not None]
    loss_pct = 0.0 if not samples else round(100.0 * (len(samples) - len(answered)) / len(samples), 1)
    if not answered:
        return {"min_ms": None, "avg_ms": None, "max_ms": None, "jitter_ms": None, "loss_pct": loss_pct}
    return {
        "min_ms": round(min(answered), 2),
        "avg_ms": round(sum(answered) / len(answered), 2),
        "max_ms": round(max(answered), 2),
        "jitter_ms": round(compute_jitter(answered), 2),
        "loss_pct": loss_pct,
    }


def throughput_mbps(byte_count: int, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return round(byte_count * 8 / seconds / 1_000_000, 2)


async def run_speed_test(state: "RadarState") -> None:
    """Run all speed test phases, streaming partial results into state."""
    if state.demo_mode:
        await _run_demo(state)
        return
    try:
        await _run_live(state)
    except Exception as exc:
        LOGGER.warning("Live speed test failed (%s); falling back to demo run", exc)
        await state.add_system_event(
            "speedtest-fallback",
            f"Live speed test unavailable ({type(exc).__name__}: {exc}). Using simulated run.",
        )
        try:
            await _run_demo(state)
        except Exception as demo_exc:
            LOGGER.warning("Demo speed test failed: %s", demo_exc)
            await state.update_speedtest(
                status="failed",
                phase=None,
                message=f"Speed test failed: {demo_exc}",
                finished=True,
            )


async def _run_live(state: "RadarState") -> None:
    await state.update_speedtest(
        status="running",
        phase="latency",
        progress=5,
        server="Cloudflare (speed.cloudflare.com)",
        message="Measuring latency…",
    )
    samples = await asyncio.to_thread(_tcp_latency_samples, LATENCY_HOST, LATENCY_PORT, LATENCY_PROBES)
    summary = summarize_rtts(samples)
    if summary["avg_ms"] is None:
        raise RuntimeError("Latency probes all failed — network may be blocked")

    await state.update_speedtest(
        phase="download",
        progress=0,
        latency_ms=summary["avg_ms"],
        jitter_ms=summary["jitter_ms"],
        packet_loss_pct=summary["loss_pct"],
        message="Measuring download…",
    )

    loop = asyncio.get_running_loop()

    def report(phase: str) -> Callable[[float, float], None]:
        def _cb(progress: float, mbps: float) -> None:
            asyncio.run_coroutine_threadsafe(
                state.update_speedtest(phase=phase, progress=round(progress, 1), current_mbps=round(mbps, 2)),
                loop,
            )

        return _cb

    down_bytes, down_seconds = await asyncio.to_thread(_measure_download, report("download"))
    if down_bytes < 50_000:
        raise RuntimeError(f"Download too small ({down_bytes} bytes) — endpoint may have blocked the request")
    download_mbps = throughput_mbps(down_bytes, down_seconds)
    await state.update_speedtest(
        phase="upload", progress=0, download_mbps=download_mbps, current_mbps=None, message="Measuring upload…"
    )

    up_bytes, up_seconds = await asyncio.to_thread(_measure_upload, report("upload"))
    if up_bytes < 50_000:
        raise RuntimeError(f"Upload too small ({up_bytes} bytes)")
    upload_mbps = throughput_mbps(up_bytes, up_seconds)
    await state.update_speedtest(
        status="complete",
        phase=None,
        progress=100,
        upload_mbps=upload_mbps,
        current_mbps=None,
        message=None,
        finished=True,
    )


async def _run_demo(state: "RadarState") -> None:
    rng = random.Random()
    await state.update_speedtest(
        status="running",
        phase="latency",
        progress=10,
        server="Simulated (demo mode)",
        message="Measuring latency…",
    )
    await asyncio.sleep(0.8)
    latency = round(rng.uniform(9.0, 16.0), 2)
    jitter = round(rng.uniform(0.6, 2.4), 2)
    await state.update_speedtest(
        phase="download",
        progress=0,
        latency_ms=latency,
        jitter_ms=jitter,
        packet_loss_pct=0.0,
        message="Measuring download…",
    )
    download_target = rng.uniform(720.0, 940.0)
    for step in range(1, 11):
        await asyncio.sleep(0.25)
        wobble = download_target * rng.uniform(0.82, 1.08)
        await state.update_speedtest(phase="download", progress=step * 10, current_mbps=round(wobble, 1))
    download = round(download_target, 1)
    await state.update_speedtest(
        phase="upload", progress=0, download_mbps=download, current_mbps=None, message="Measuring upload…"
    )
    upload_target = rng.uniform(32.0, 48.0)
    for step in range(1, 9):
        await asyncio.sleep(0.22)
        wobble = upload_target * rng.uniform(0.8, 1.1)
        await state.update_speedtest(phase="upload", progress=step * 12.5, current_mbps=round(wobble, 1))
    await state.update_speedtest(
        status="complete",
        phase=None,
        progress=100,
        upload_mbps=round(upload_target, 1),
        current_mbps=None,
        message=None,
        finished=True,
    )


def _tcp_latency_samples(host: str, port: int, count: int, timeout: float = 2.0) -> list[float | None]:
    samples: list[float | None] = []
    for _ in range(count):
        start = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                samples.append((time.perf_counter() - start) * 1000.0)
        except OSError:
            samples.append(None)
        time.sleep(0.05)
    return samples


def _measure_download(progress_cb: Callable[[float, float], None]) -> tuple[int, float]:
    url = DOWNLOAD_URL.format(size=DOWNLOAD_BYTES)
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    received = 0
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=MAX_PHASE_SECONDS + 8) as response:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                elapsed = time.perf_counter() - start
                progress_cb(
                    min(100.0, 100.0 * received / DOWNLOAD_BYTES),
                    (received * 8 / max(elapsed, 1e-6)) / 1e6,
                )
                if elapsed > MAX_PHASE_SECONDS:
                    break
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Download HTTP {exc.code}") from exc
    return received, time.perf_counter() - start


def _measure_upload(progress_cb: Callable[[float, float], None]) -> tuple[int, float]:
    # Fixed pattern is far faster than filling with getrandbits() and is fine for throughput.
    payload = b"0123456789abcdef" * (UPLOAD_BYTES // 16)
    request = urllib.request.Request(
        UPLOAD_URL,
        data=payload,
        method="POST",
        headers={**REQUEST_HEADERS, "Content-Type": "application/octet-stream"},
    )
    start = time.perf_counter()
    progress_cb(20.0, 0.0)
    try:
        with urllib.request.urlopen(request, timeout=MAX_PHASE_SECONDS + 8):
            pass
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Upload HTTP {exc.code}") from exc
    elapsed = time.perf_counter() - start
    progress_cb(100.0, (len(payload) * 8 / max(elapsed, 1e-6)) / 1e6)
    return len(payload), elapsed


def demo_speedtest_result() -> dict[str, Any]:
    """One-shot simulated result (used by tests)."""
    rng = random.Random(7)
    return {
        "latency_ms": round(rng.uniform(9.0, 16.0), 2),
        "jitter_ms": round(rng.uniform(0.6, 2.4), 2),
        "packet_loss_pct": 0.0,
        "download_mbps": round(rng.uniform(720.0, 940.0), 1),
        "upload_mbps": round(rng.uniform(32.0, 48.0), 1),
    }
