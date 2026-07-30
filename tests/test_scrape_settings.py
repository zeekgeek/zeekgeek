"""Tests for BrowserClaw scrape mode resolution."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from etsy_ai_space.scraper.scrape_settings import resolve_scrape_settings


class ScrapeSettingsTests(unittest.TestCase):
    def test_demo_mode_when_demo_flag_set(self) -> None:
        settings = resolve_scrape_settings(demo=True, scrape_mode="browserclaw")
        self.assertTrue(settings.use_demo)
        self.assertEqual(settings.scrape_mode, "demo")

    @patch("etsy_ai_space.scraper.scrape_settings.probe_cdp_url", return_value=True)
    @patch("etsy_ai_space.scraper.scrape_settings.resolve_cdp_url", return_value="http://127.0.0.1:18800")
    def test_browserclaw_mode_uses_cdp(self, _resolve, _probe) -> None:
        settings = resolve_scrape_settings(
            demo=False,
            scrape_mode="browserclaw",
            cdp_url="18800",
            reuse_browser_tab=True,
        )
        self.assertFalse(settings.use_demo)
        self.assertEqual(settings.scrape_mode, "browserclaw")
        self.assertEqual(settings.cdp_url, "http://127.0.0.1:18800")
        self.assertTrue(settings.reuse_browser_tab)

    @patch("etsy_ai_space.scraper.scrape_settings.discover_cdp_url", return_value=None)
    @patch("etsy_ai_space.scraper.scrape_settings.probe_cdp_url", return_value=False)
    @patch("etsy_ai_space.scraper.scrape_settings.resolve_cdp_url", return_value="http://127.0.0.1:18800")
    def test_browserclaw_falls_back_to_demo(self, _resolve, _probe, _discover) -> None:
        settings = resolve_scrape_settings(
            demo=False,
            scrape_mode="browserclaw",
            cdp_fallback_demo=True,
        )
        self.assertTrue(settings.use_demo)
        self.assertTrue(settings.cdp_fallback)

    def test_playwright_mode(self) -> None:
        settings = resolve_scrape_settings(demo=False, scrape_mode="playwright")
        self.assertFalse(settings.use_demo)
        self.assertEqual(settings.scrape_mode, "playwright")
        self.assertIsNone(settings.cdp_url)


if __name__ == "__main__":
    unittest.main()
