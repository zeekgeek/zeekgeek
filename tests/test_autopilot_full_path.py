"""Tests for n8n-style autopilot: approve → image → Printify."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from etsy_ai_space.agents.openai_image_generator import (
    placeholder_png_bytes,
    resolve_image_provider,
)
from etsy_ai_space.db import StoreDatabase
from etsy_ai_space.pipeline.autopilot import AutopilotConfig, AutopilotRunner
from etsy_ai_space.pipeline.state_tracker import SwarmStateTracker


class FakePrintifyClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.published: list[str] = []
        self._n = 0

    def list_shops(self) -> list[dict[str, Any]]:
        return [{"id": 4242, "title": "Demo"}]

    def list_variants(self, blueprint_id: int, print_provider_id: int) -> list[dict[str, Any]]:
        return [
            {"id": 101, "title": "Black / M", "options": {"color": "Black", "size": "M"}},
        ]

    def upload_image_file(self, path: Path, *, file_name: str | None = None) -> dict[str, Any]:
        return {"id": "img-1", "file_name": file_name or Path(path).name}

    def create_product(self, shop_id: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        self._n += 1
        pid = f"prod-{self._n}"
        self.created.append({"id": pid, "shop_id": shop_id, "payload": payload})
        return {"id": pid, "title": payload.get("title")}

    def publish_product(self, shop_id: int | str, product_id: str, **kwargs: Any) -> dict[str, Any]:
        self.published.append(str(product_id))
        return {}


class AutopilotFullPathTests(unittest.IsolatedAsyncioTestCase):
    def test_placeholder_png_is_valid_header(self) -> None:
        data = placeholder_png_bytes()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(data), 40)

    def test_resolve_image_provider_falls_back_without_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_image_provider("openai", demo_mode=True), "demo")
            self.assertEqual(resolve_image_provider("openai", demo_mode=False), "demo")
            self.assertEqual(resolve_image_provider("demo", demo_mode=False), "demo")

    def test_config_loads_full_auto_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autopilot.yaml"
            path.write_text(
                "\n".join(
                    [
                        "niches: [retro cat shirt]",
                        "demo: true",
                        "auto_approve: true",
                        "auto_generate_images: true",
                        "auto_printify: true",
                        "printify_publish: true",
                        "require_manual_upload: false",
                        "uploads_per_cycle: 2",
                        "image_provider: demo",
                    ]
                ),
                encoding="utf-8",
            )
            config = AutopilotConfig.load(path)
            self.assertTrue(config.auto_approve)
            self.assertTrue(config.auto_generate_images)
            self.assertTrue(config.auto_printify)
            self.assertTrue(config.printify_publish)
            self.assertFalse(config.require_manual_upload)
            self.assertEqual(config.uploads_per_cycle, 2)

    async def test_full_cycle_demo_images_and_printify_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            export_dir = Path(tmp) / "exports"
            tracker = SwarmStateTracker(
                state_path=Path(tmp) / "state.json",
                log_path=Path(tmp) / "system.log",
            )
            config = AutopilotConfig(
                niches=["retro cat shirt"],
                demo=True,
                max_cycles_per_day=2,
                concepts_per_cycle=5,
                auto_approve=True,
                auto_generate_images=True,
                auto_printify=True,
                printify_publish=True,
                require_manual_upload=False,
                uploads_per_cycle=2,
                image_provider="demo",
                printify={"shop_id": 4242},
            )
            fake = FakePrintifyClient()
            # Point PrintifyConfig.load at a temp yaml so product_types match the fake client
            yaml_path = Path(tmp) / "autopilot.yaml"
            yaml_path.write_text(
                "\n".join(
                    [
                        "require_manual_upload: false",
                        "daily_upload_cap: 5",
                        "printify:",
                        "  shop_id: 4242",
                        "  product_types:",
                        "    - key: tshirt",
                        "      blueprint_id: 6",
                        "      print_provider_id: 99",
                        "      colors: [Black]",
                    ]
                ),
                encoding="utf-8",
            )
            runner = AutopilotRunner(
                db,
                config,
                tracker=tracker,
                export_dir=export_dir,
                printify_client=fake,
            )
            with patch("etsy_ai_space.printify.uploader.DEFAULT_CONFIG", yaml_path):
                with patch("etsy_ai_space.pipeline.autopilot.DEFAULT_CONFIG_PATH", yaml_path):
                    result = await runner.run_cycle()

            self.assertEqual(result["concepts"], 5)
            # Orchestrator already exports drafts as approved→exported; approve may be 0.
            self.assertIn(result["auto_approved"], (0, 5))
            self.assertEqual(result["images"]["generated"], 2)
            self.assertEqual(result["printify"]["uploaded"], 2)
            self.assertTrue(result["printify"]["published"])
            self.assertEqual(len(fake.created), 2)
            self.assertEqual(len(fake.published), 2)
            published = db.listing_drafts(status="etsy_published")
            self.assertEqual(len(published), 2)

    async def test_printify_publish_blocked_when_manual_gate_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            export_dir = Path(tmp) / "exports"
            config = AutopilotConfig(
                niches=["retro cat shirt"],
                demo=True,
                concepts_per_cycle=3,
                auto_approve=True,
                auto_generate_images=True,
                auto_printify=True,
                printify_publish=True,
                require_manual_upload=True,
                uploads_per_cycle=1,
                image_provider="demo",
            )
            fake = FakePrintifyClient()
            yaml_path = Path(tmp) / "autopilot.yaml"
            yaml_path.write_text(
                "require_manual_upload: true\ndaily_upload_cap: 5\n"
                "printify:\n  shop_id: 4242\n  product_types:\n"
                "    - {key: tshirt, blueprint_id: 6, print_provider_id: 99, colors: [Black]}\n",
                encoding="utf-8",
            )
            runner = AutopilotRunner(
                db,
                config,
                export_dir=export_dir,
                printify_client=fake,
            )
            with patch("etsy_ai_space.printify.uploader.DEFAULT_CONFIG", yaml_path):
                result = await runner.run_cycle()
            self.assertEqual(result["printify"]["uploaded"], 1)
            self.assertFalse(result["printify"]["published"])
            self.assertEqual(fake.published, [])
            self.assertEqual(len(db.listing_drafts(status="etsy_draft")), 1)


if __name__ == "__main__":
    unittest.main()
