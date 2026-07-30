"""Tests for building Cursor CLI image-generation scripts (SwarmAssets)."""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from etsy_ai_space.tools.swarm_assets import (
    build_asset_jobs,
    build_cli_commands,
    build_image_description,
    slugify,
    write_run_script,
)


SAMPLE_PACK = {
    "listings": [
        {
            "title": "Recovery Definition Shirt, Dictionary Style Sobriety Tee",
            "status": "pending_review",
            "image_prompt": (
                "=== STYLE: definition ===\n\n"
                "SHIRT TEXT (type this exactly in Canva):\n"
                "recovery | noun\nchoosing yourself\n\n"
                "--- CANVA ---\nType the text."
            ),
        },
        {
            "title": "We Do Recover Shirt",
            "status": "approved_for_export",
            "image_prompt": "=== STYLE: minimal ===\n\nSHIRT TEXT (type this exactly in Canva):\nwe do recover.\n\n---",
        },
    ]
}


class SwarmAssetsTests(unittest.TestCase):
    def test_slugify(self) -> None:
        self.assertEqual(slugify("Recovery Definition Shirt!"), "recovery_definition_shirt")

    def test_build_image_description_includes_shirt_text(self) -> None:
        description = build_image_description(SAMPLE_PACK["listings"][0])
        self.assertIn("recovery | noun", description)
        self.assertIn("transparent", description.lower())

    def test_build_asset_jobs_from_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_path = Path(tmp) / "design-pack.json"
            pack_path.write_text(json.dumps(SAMPLE_PACK), encoding="utf-8")
            jobs = build_asset_jobs(pack_path)
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["slug"], "recovery_definition_shirt_dictionary_style_sobriety_tee")
            self.assertIn("choosing yourself", jobs[0]["description"])

    def test_build_cli_commands_reference_target_path(self) -> None:
        jobs = build_asset_jobs_from_dict(SAMPLE_PACK)
        commands = build_cli_commands(jobs, out_dir="$HOME/SwarmAssets")
        self.assertEqual(len(commands), 2)
        self.assertIn("cursor-agent", commands[0])
        self.assertIn("$HOME/SwarmAssets", commands[0])
        self.assertIn(jobs[0]["slug"], commands[0])

    def test_write_run_script_is_executable_and_contains_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_path = Path(tmp) / "design-pack.json"
            pack_path.write_text(json.dumps(SAMPLE_PACK), encoding="utf-8")
            script_path = Path(tmp) / "generate_swarm_assets.sh"

            result = write_run_script(pack_path, script_path, out_dir="$HOME/SwarmAssets")

            self.assertTrue(result.exists())
            mode = result.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR)
            content = result.read_text(encoding="utf-8")
            self.assertIn("#!/bin/bash", content)
            self.assertIn("cursor-agent", content)
            self.assertIn("mkdir -p", content)
            self.assertIn("SwarmAssets", content)
            self.assertEqual(content.count("cursor-agent -p --force"), 2)


def build_asset_jobs_from_dict(pack: dict) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        pack_path = Path(tmp) / "design-pack.json"
        pack_path.write_text(json.dumps(pack), encoding="utf-8")
        return build_asset_jobs(pack_path)


if __name__ == "__main__":
    unittest.main()
