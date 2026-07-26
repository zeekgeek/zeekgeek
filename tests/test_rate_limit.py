"""Tests for Etsy scraper rate limiting."""

from __future__ import annotations

import unittest

from etsy_ai_space.scraper.rate_limit import (
    BACKOFF_INITIAL_SECONDS,
    BACKOFF_MAX_SECONDS,
    EtsyRateLimiter,
    compute_backoff_seconds,
    domain_from_url,
    parse_retry_after,
)


class RateLimitTests(unittest.TestCase):
    def test_domain_from_url(self) -> None:
        self.assertEqual(domain_from_url("https://www.etsy.com/search?q=cat"), "etsy.com")

    def test_parse_retry_after_seconds(self) -> None:
        self.assertEqual(parse_retry_after({"Retry-After": "45"}), 45.0)

    def test_backoff_respects_retry_after(self) -> None:
        delay = compute_backoff_seconds(1, retry_after=120.0)
        self.assertGreaterEqual(delay, 120.0)
        self.assertLessEqual(delay, BACKOFF_MAX_SECONDS)

    def test_backoff_caps_at_max(self) -> None:
        delay = compute_backoff_seconds(20)
        self.assertLessEqual(delay, BACKOFF_MAX_SECONDS)
        self.assertGreaterEqual(delay, BACKOFF_INITIAL_SECONDS)

    def test_inter_request_delay_enforces_minimum(self) -> None:
        limiter = EtsyRateLimiter(min_delay=3.0, max_delay=6.0)
        for _ in range(20):
            delay = limiter._inter_request_delay()
            self.assertGreaterEqual(delay, 3.0)

    def test_token_bucket_wait_when_full(self) -> None:
        import time

        limiter = EtsyRateLimiter(max_requests_per_minute=2)
        now = time.monotonic()
        limiter._request_times.append(now - 10)
        limiter._request_times.append(now - 5)
        wait = limiter._token_bucket_wait()
        self.assertGreater(wait, 0.0)


if __name__ == "__main__":
    unittest.main()
