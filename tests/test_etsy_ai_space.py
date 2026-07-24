"""Tests for the Etsy AI Space phased swarm."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from etsy_ai_space.agents.designer.workers import expand_listing_copy
from etsy_ai_space.agents.researcher.runner import run_researcher
from etsy_ai_space.db import StoreDatabase
from etsy_ai_space.export.bundle import export_pending_drafts
from etsy_ai_space.models import CreativeBrief, ListingDraft
from etsy_ai_space.scraper.demo import DemoScraperBackend
from etsy_ai_space.tools.humanize import humanize_text


class EtsyAiSpaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_researcher_stores_demo_listings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            result = await run_researcher(
                "retro cat shirt",
                db,
                backend=DemoScraperBackend(),
                max_results=10,
                min_score=0.0,
            )
            self.assertGreaterEqual(result["stored"], 1)
            top = db.top_listings(limit=5)
            self.assertTrue(top)
            self.assertIn("title", top[0])

    def test_humanize_flags_generic_copy(self) -> None:
        report = humanize_text(
            "Perfect Gift",
            "A unique design and high quality shirt. Ideal for any occasion.",
            ["gift", "unique", "cool"],
        )
        self.assertFalse(report.passed)
        self.assertTrue(report.issues)

    def test_designer_worker_builds_listing(self) -> None:
        brief = CreativeBrief(
            trend_summary="Retro cats trending",
            niche="retro cat shirt",
            target_buyer="Cat moms",
            design_direction="Minimal line-art cat with sunset circle",
            color_palette=["orange", "cream"],
        )
        draft = expand_listing_copy(brief)
        self.assertGreaterEqual(len(draft.tags), 8)
        self.assertIn("cat", draft.title.lower())

    def test_export_writes_json_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            db.save_listing_draft(
                ListingDraft(
                    title="Test Listing Title Here",
                    description="Specific description without generic filler phrases for testing.",
                    tags=[
                        "retro cat shirt",
                        "vintage tee",
                        "sunset graphic",
                        "cat mom gift",
                        "line art cat",
                        "minimalist tee",
                        "neutral aesthetic",
                        "printed to order",
                    ],
                    price=24.99,
                    image_prompt="Flat cat graphic, transparent background",
                    status="approved_for_export",
                )
            )
            out_dir = Path(tmp) / "exports"
            paths = export_pending_drafts(db, out_dir)
            self.assertTrue(Path(paths["json"]).exists())
            self.assertTrue(Path(paths["csv"]).exists())
            payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["count"], 1)


if __name__ == "__main__":
    unittest.main()
