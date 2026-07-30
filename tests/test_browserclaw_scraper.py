"""Tests for BrowserClaw CDP attach and niche loading."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from etsy_ai_space.scraper.browser_connect import (
    discover_cdp_url,
    normalize_cdp_url,
    probe_cdp_url,
    resolve_cdp_url,
)
from etsy_ai_space.scraper.browserclaw_scraper import load_niches
from etsy_ai_space.scraper.playwright import PlaywrightScraperBackend


class BrowserClawScraperTests(unittest.TestCase):
    def test_normalize_http_and_ws_urls(self) -> None:
        self.assertEqual(normalize_cdp_url("9222"), "http://127.0.0.1:9222")
        self.assertEqual(normalize_cdp_url("18800"), "http://127.0.0.1:18800")
        self.assertEqual(normalize_cdp_url("127.0.0.1:9222"), "http://127.0.0.1:9222")
        self.assertEqual(
            normalize_cdp_url("http://127.0.0.1:9222"),
            "http://127.0.0.1:9222",
        )
        ws = "ws://127.0.0.1:9222/devtools/browser/abc"
        self.assertEqual(normalize_cdp_url(ws), ws)

    def test_resolve_cdp_url_prefers_explicit(self) -> None:
        self.assertEqual(
            resolve_cdp_url("ws://127.0.0.1:9333/devtools/browser/test"),
            "ws://127.0.0.1:9333/devtools/browser/test",
        )

    def test_load_niches_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "autopilot.yaml"
            config.write_text(
                "niches:\n  - soberversary shirt gift\n  - recovery definition shirt\n",
                encoding="utf-8",
            )
            niches = load_niches(config)
            self.assertEqual(len(niches), 2)
            self.assertIn("soberversary shirt gift", niches)

    def test_playwright_backend_source_when_cdp(self) -> None:
        backend = PlaywrightScraperBackend(cdp_url="http://127.0.0.1:9222")
        self.assertEqual(backend.source, "browserclaw")

    def test_probe_cdp_returns_none_when_offline(self) -> None:
        self.assertIsNone(probe_cdp_url("http://127.0.0.1:1", timeout=0.2))

    def test_discover_cdp_returns_none_when_offline(self) -> None:
        self.assertIsNone(discover_cdp_url(ports=(1, 2)))

    def test_parse_signals_extracts_reviews_rating(self) -> None:
        text = "Custom Tee 4.9 (352 reviews) $24.99 Bestseller"
        reviews, rating, favorites = PlaywrightScraperBackend._parse_signals(text)
        self.assertEqual(reviews, 352)
        self.assertEqual(rating, 4.9)
        self.assertIsNone(favorites)


if __name__ == "__main__":
    unittest.main()
