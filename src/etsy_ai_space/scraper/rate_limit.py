"""Polite rate limiting for Etsy scraping (no login).

Adjust the constants below to tune scraping speed and resilience.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limit configuration — edit these values to tune politeness
# ---------------------------------------------------------------------------
ETSY_DOMAIN = "etsy.com"

# Hard minimum gap between requests to the same domain (seconds)
MIN_DELAY_SECONDS = 3.0
MAX_DELAY_SECONDS = 6.0

# Extra random jitter so timing is not perfectly regular (± seconds)
JITTER_MIN_SECONDS = 1.0
JITTER_MAX_SECONDS = 2.0

# Token-bucket style cap (requests per rolling minute)
MAX_REQUESTS_PER_MINUTE = 12

# Exponential backoff for 429 / 503 / connection errors
BACKOFF_INITIAL_SECONDS = 30.0
BACKOFF_MAX_SECONDS = 600.0  # 10 minutes
BACKOFF_MULTIPLIER = 2.0
BACKOFF_JITTER_FRACTION = 0.25
MAX_RETRIES = 8

RETRY_STATUS_CODES = frozenset({429, 503})


def domain_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def parse_retry_after(headers: dict[str, str] | Any) -> float | None:
    """Parse Retry-After header (seconds or HTTP-date)."""
    if not headers:
        return None
    raw = None
    if hasattr(headers, "get"):
        raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    raw = str(raw).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def compute_backoff_seconds(attempt: int, *, retry_after: float | None = None) -> float:
    """Exponential backoff with jitter, capped at BACKOFF_MAX_SECONDS."""
    base = BACKOFF_INITIAL_SECONDS * (BACKOFF_MULTIPLIER ** max(0, attempt - 1))
    base = min(base, BACKOFF_MAX_SECONDS)
    jitter = base * BACKOFF_JITTER_FRACTION * random.random()
    delay = base + jitter
    if retry_after is not None:
        delay = max(delay, retry_after)
    return min(delay, BACKOFF_MAX_SECONDS)


@dataclass
class RateLimitStats:
    requests: int = 0
    rate_limit_events: int = 0
    total_sleep_seconds: float = 0.0


@dataclass
class EtsyRateLimiter:
    """Sleep-based + token-bucket limiter with concurrency=1."""

    min_delay: float = MIN_DELAY_SECONDS
    max_delay: float = MAX_DELAY_SECONDS
    jitter_min: float = JITTER_MIN_SECONDS
    jitter_max: float = JITTER_MAX_SECONDS
    max_requests_per_minute: int = MAX_REQUESTS_PER_MINUTE
    max_retries: int = MAX_RETRIES
    domain: str = ETSY_DOMAIN

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _last_request_at: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _request_times: deque[float] = field(default_factory=deque, init=False, repr=False)
    stats: RateLimitStats = field(default_factory=RateLimitStats, init=False)

    def _inter_request_delay(self) -> float:
        base = random.uniform(self.min_delay, self.max_delay)
        jitter = random.uniform(-self.jitter_max, self.jitter_max)
        if abs(jitter) < self.jitter_min:
            jitter = self.jitter_min if jitter >= 0 else -self.jitter_min
        delay = max(self.min_delay, base + jitter)
        return delay

    def _token_bucket_wait(self) -> float:
        now = time.monotonic()
        window = 60.0
        while self._request_times and now - self._request_times[0] > window:
            self._request_times.popleft()
        if len(self._request_times) < self.max_requests_per_minute:
            return 0.0
        oldest = self._request_times[0]
        return max(0.0, window - (now - oldest) + 0.05)

    async def wait_before_request(self, url: str) -> float:
        """Apply domain spacing + token bucket; return total sleep applied."""
        host = domain_from_url(url)
        if ETSY_DOMAIN not in host:
            LOGGER.debug("rate-limit: skipping limiter for off-domain URL %s", url)
            return 0.0

        total_sleep = 0.0

        bucket_wait = self._token_bucket_wait()
        if bucket_wait > 0:
            self.stats.rate_limit_events += 1
            LOGGER.warning(
                "rate-limit: token bucket full (%d/min); sleeping %.2fs before %s",
                self.max_requests_per_minute,
                bucket_wait,
                url,
            )
            await asyncio.sleep(bucket_wait)
            total_sleep += bucket_wait

        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            required = self._inter_request_delay()
            if elapsed < required:
                sleep_for = required - elapsed
                self.stats.rate_limit_events += 1
                LOGGER.info(
                    "rate-limit: domain spacing; sleeping %.2fs (min %.1f–%.1fs + jitter) before %s",
                    sleep_for,
                    self.min_delay,
                    self.max_delay,
                    url,
                )
                await asyncio.sleep(sleep_for)
                total_sleep += sleep_for

        return total_sleep

    def record_request(self, url: str, *, status_code: int | None = None) -> None:
        now = time.monotonic()
        host = domain_from_url(url)
        self._last_request_at[host] = now
        self._request_times.append(now)
        self.stats.requests += 1
        if status_code is not None:
            LOGGER.info("rate-limit: request completed url=%s status=%d", url, status_code)

    async def sleep_backoff(
        self,
        url: str,
        *,
        attempt: int,
        status_code: int | None = None,
        retry_after: float | None = None,
        error: str | None = None,
    ) -> float:
        delay = compute_backoff_seconds(attempt, retry_after=retry_after)
        self.stats.rate_limit_events += 1
        self.stats.total_sleep_seconds += delay
        if status_code in RETRY_STATUS_CODES:
            LOGGER.warning(
                "rate-limit: HTTP %d on %s; exponential backoff %.2fs (attempt %d/%d, retry-after=%s)",
                status_code,
                url,
                delay,
                attempt,
                self.max_retries,
                retry_after,
            )
        else:
            LOGGER.warning(
                "rate-limit: connection error on %s (%s); backoff %.2fs (attempt %d/%d)",
                url,
                error or "unknown",
                delay,
                attempt,
                self.max_retries,
            )
        await asyncio.sleep(delay)
        return delay

    def slot(self) -> asyncio.Lock:
        """Concurrency gate — only one in-flight Etsy request at a time."""
        return self._lock


async def polite_goto(
    page: Any,
    url: str,
    limiter: EtsyRateLimiter | None = None,
    **goto_kwargs: Any,
) -> Any:
    """Wrap Playwright page.goto with rate limiting, retries, and backoff."""
    gate = limiter or EtsyRateLimiter()
    attempt = 0
    last_exc: Exception | None = None

    while attempt < gate.max_retries:
        attempt += 1
        async with gate.slot():
            slept = await gate.wait_before_request(url)
            if slept:
                gate.stats.total_sleep_seconds += slept
            try:
                response = await page.goto(url, **goto_kwargs)
            except Exception as exc:
                last_exc = exc
                await gate.sleep_backoff(url, attempt=attempt, error=str(exc))
                continue

            status = response.status if response is not None else 0
            gate.record_request(url, status_code=status)

            if status in RETRY_STATUS_CODES:
                retry_after = None
                if response is not None:
                    retry_after = parse_retry_after(response.headers)
                await gate.sleep_backoff(
                    url,
                    attempt=attempt,
                    status_code=status,
                    retry_after=retry_after,
                )
                continue

            if status >= 400:
                LOGGER.warning("rate-limit: HTTP %d on %s (no retry configured)", status, url)

            return response

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"rate-limit: exhausted {gate.max_retries} retries for {url}")
