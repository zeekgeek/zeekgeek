"""Tests for BrowserClaw → Printify staging helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from etsy_ai_space.scraper.browserclaw_printify import run_browserclaw_printify


class BrowserclawPrintifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_lists_packages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "listing-03"
            images = package / "images"
            images.mkdir(parents=True)
            (images / "01-printify-print.png").write_bytes(b"img")
            (package / "listing.json").write_text(
                json.dumps(
                    {
                        "listing_number": 3,
                        "title": "When We Recover Loudly",
                        "description": "Bold phoenix tee",
                        "tags": ["recovery shirt"],
                        "price_usd": 26.99,
                    }
                ),
                encoding="utf-8",
            )
            result = await run_browserclaw_printify(
                [package],
                cdp_url="9222",
                dry_run=True,
            )
            self.assertTrue(result["dry_run"])
            self.assertEqual(len(result["jobs"]), 1)
            self.assertEqual(result["jobs"][0]["action"], "stage_printify_draft")
            self.assertIn("BrowserClaw", result["next_step"])


if __name__ == "__main__":
    unittest.main()
