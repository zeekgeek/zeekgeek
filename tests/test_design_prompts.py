"""Tests for recovery POD design brief generation."""

from __future__ import annotations

import unittest

from etsy_ai_space.agents.design_prompts import build_recovery_design_brief
from etsy_ai_space.models import ProductConcept


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


if __name__ == "__main__":
    unittest.main()
