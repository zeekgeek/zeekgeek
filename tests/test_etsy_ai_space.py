"""Tests for the Etsy AI Space phased swarm."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from etsy_ai_space.agents.designer.workers import expand_listing_copy
from etsy_ai_space.agents.workers import copywriter_agent, design_agent, seo_agent, workers_build_listing
from etsy_ai_space.agents.researcher.runner import run_researcher
from etsy_ai_space.db import StoreDatabase
from etsy_ai_space.export.bundle import export_pending_drafts
from etsy_ai_space.models import CreativeBrief, ListingDraft, ProductConcept
from etsy_ai_space.pipeline.autopilot import AutopilotConfig, AutopilotRunner
from etsy_ai_space.pipeline.orchestrator import ManagerAgent, run_orchestrator
from etsy_ai_space.pipeline.state_tracker import SwarmStateTracker, default_state
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

    def test_worker_agents_build_listing(self) -> None:
        concept = ProductConcept(
            concept_name="Retro Cat Sunset",
            hook="For cat moms who want a specific vintage vibe",
            angle="minimal line-art cat with sunset circle",
            trend_summary="Retro cat shirts trending with high review counts",
        )
        copy = copywriter_agent(concept)
        design = design_agent(concept)
        seo = seo_agent(concept, copy.title)
        self.assertIn("Retro Cat", copy.title)
        self.assertIn("CANVA", design.midjourney_prompt)
        self.assertTrue(design.shirt_text)
        self.assertGreaterEqual(len(seo.tags), 5)

        draft = workers_build_listing(concept)
        self.assertGreaterEqual(len(draft.tags), 5)
        self.assertIn("print-ready", draft.image_prompt.lower())

    def test_manager_generates_five_concepts(self) -> None:
        manager = ManagerAgent()
        top = [
            {
                "title": "Retro Cat Shirt",
                "tags": ["retro cat", "vintage tee"],
                "price_amount": 24.99,
                "etsy_listing_id": "123",
            }
        ]
        concepts = manager.generate_concepts("retro cat shirt", top, count=5)
        self.assertEqual(len(concepts), 5)
        self.assertTrue(all(c.concept_name for c in concepts))

    async def test_orchestrator_end_to_end_demo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            state_path = Path(tmp) / "state.json"
            log_path = Path(tmp) / "system.log"
            tracker = SwarmStateTracker(state_path=state_path, log_path=log_path)
            result = await run_orchestrator(
                "retro cat shirt",
                db,
                demo=True,
                concept_count=5,
                export_dir=Path(tmp) / "exports",
                tracker=tracker,
            )
            self.assertEqual(len(result["concepts"]), 5)
            self.assertEqual(len(result["drafts"]), 5)
            self.assertTrue(Path(result["export"]["json"]).exists())
            loaded = tracker.load()
            self.assertGreater(len(loaded["logs"]), 2)
            self.assertEqual(len(loaded["agents"]), 5)

    def test_state_tracker_writes_json_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = SwarmStateTracker(
                state_path=Path(tmp) / "state.json",
                log_path=Path(tmp) / "system.log",
            )
            with tracker.agent_activity("Scraper", "Scraping"):
                tracker.log("Test scrape complete")
            state = tracker.load()
            self.assertTrue((Path(tmp) / "state.json").exists())
            scraper = next(a for a in state["agents"] if a["name"] == "Scraper")
            self.assertEqual(scraper["success_count"], 1)
            self.assertIn("Test scrape complete", tracker.tail_log_file())

    def test_default_state_schema(self) -> None:
        state = default_state()
        self.assertIn("metrics", state)
        self.assertEqual(len(state["agents"]), 5)
        self.assertIn("listings_generated", state["metrics"])

    def test_autopilot_config_loads(self) -> None:
        config = AutopilotConfig.load(Path("/workspace/etsy_ai_space/autopilot.yaml"))
        self.assertGreaterEqual(len(config.niches), 5)
        self.assertIn("recovery definition shirt", config.niches)
        self.assertIn("soberversary shirt custom date", config.niches)
        self.assertTrue(config.demo)

    async def test_autopilot_single_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            config = AutopilotConfig(niches=["retro cat shirt"], demo=True, max_cycles_per_day=2)
            runner = AutopilotRunner(db, config, export_dir=Path(tmp) / "exports")
            result = await runner.run_cycle()
            self.assertEqual(result["concepts"], 5)
            self.assertIn("export", result)

    def test_designer_worker_builds_listing(self) -> None:
        brief = CreativeBrief(
            trend_summary="Retro cats trending",
            niche="retro cat shirt",
            target_buyer="Cat moms",
            design_direction="Minimal line-art cat with sunset circle",
            color_palette=["orange", "cream"],
        )
        draft = expand_listing_copy(brief)
        self.assertGreaterEqual(len(draft.tags), 5)
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
