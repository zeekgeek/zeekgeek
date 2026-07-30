"""Tests for recovery POD design brief generation."""

from __future__ import annotations

import unittest

from etsy_ai_space.agents.design_prompts import _pick_style, build_recovery_design_brief
from etsy_ai_space.agents.workers import copywriter_agent, design_agent, seo_agent
from etsy_ai_space.models import ProductConcept
from etsy_ai_space.pipeline.orchestrator import CONCEPT_ANGLES, ManagerAgent
from etsy_ai_space.tools.humanize import humanize_text


class DesignPromptTests(unittest.TestCase):
    def test_definition_style_for_recovery_niche(self) -> None:
        concept = ProductConcept(
            concept_name="Recovery Definition Concept 1",
            hook="Dictionary-style original wording",
            angle="dictionary definition layout",
            trend_summary="recovery definition shirt trending",
        )
        brief = build_recovery_design_brief(concept)
        self.assertEqual(brief.style, "definition")
        self.assertIn("recovery |", brief.shirt_text)
        self.assertIn("CANVA", brief.to_image_prompt())

    def test_soberversary_style(self) -> None:
        concept = ProductConcept(
            concept_name="Soberversary Shirt Concept 2",
            hook="Custom date milestone gift",
            angle="soberversary date stamp",
            trend_summary="soberversary comfort colors",
        )
        brief = build_recovery_design_brief(concept)
        self.assertEqual(brief.style, "soberversary")
        self.assertIn("CUSTOM DATE", brief.shirt_text)

    def test_pick_style_prefers_angle_over_concept_name(self) -> None:
        concept = ProductConcept(
            concept_name="Recovery Definition Concept 4",
            hook="A fresh take on recovery definition shirt",
            angle="varsity crew typography — arched RECOVERY over CREW",
            trend_summary="recovery definition shirt trending",
        )
        self.assertEqual(_pick_style(concept), "varsity")

    def test_recovery_definition_niche_yields_distinct_styles(self) -> None:
        manager = ManagerAgent()
        manager.api_key = None
        top = [
            {
                "title": "Recovery Definition Shirt",
                "tags": ["recovery definition", "sobriety gift"],
                "price_amount": 24.99,
                "etsy_listing_id": "1",
            }
        ]
        concepts = manager.generate_concepts("recovery definition shirt", top, count=5)
        styles = [design_agent(c).design_style for c in concepts]
        self.assertEqual(len(styles), 5)
        self.assertEqual(len(set(styles)), 5)
        self.assertEqual(len(CONCEPT_ANGLES), 5)

    def test_recovery_copy_is_buyer_facing_and_passes_qc(self) -> None:
        concept = ProductConcept(
            concept_name="Definition Recovery Concept 1",
            hook="A fresh take on recovery definition shirt",
            angle="dictionary definition layout — serif blocks",
            trend_summary="recovery definition shirt",
        )
        copy = copywriter_agent(concept)
        design = design_agent(concept)
        seo = seo_agent(concept, copy.title, design_style=design.design_style)
        report = humanize_text(copy.title, copy.description, seo.tags)

        self.assertNotIn("Concept 1", copy.title)
        self.assertIn("Recovery", copy.title)
        self.assertGreaterEqual(len(seo.tags), 8)
        self.assertTrue(all(len(tag) <= 20 for tag in seo.tags))
        self.assertTrue(report.passed, report.issues)


if __name__ == "__main__":
    unittest.main()
