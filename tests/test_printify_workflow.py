"""Tests for the Printify draft-push + human-submit workflow."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from etsy_ai_space.printify.client import PrintifyError
from etsy_ai_space.printify.workflow import (
    PrintifyConfig,
    PrintifyWorkflow,
    build_product_payload,
    filter_variants,
    load_listing_package,
    load_printify_config,
    load_queue,
    save_queue,
)


class PrintifyWorkflowTests(unittest.TestCase):
    def test_load_config_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.yaml"
            config = load_printify_config(path)
            self.assertEqual(config.blueprint_id, 706)
            self.assertFalse(config.auto_publish)

    def test_load_config_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "printify.yaml"
            path.write_text(
                "shop_id: 123\nprint_provider_id: 99\nblueprint_id: 706\nauto_publish: false\n",
                encoding="utf-8",
            )
            config = load_printify_config(path)
            self.assertEqual(config.shop_id, 123)
            self.assertEqual(config.print_provider_id, 99)

    def test_filter_variants_by_color_and_size(self) -> None:
        variants = [
            {"id": 1, "title": "Black / M", "options": {"color": "Black", "size": "M"}},
            {"id": 2, "title": "Black / S", "options": {"color": "Black", "size": "S"}},
            {"id": 3, "title": "White / M", "options": {"color": "White", "size": "M"}},
            {"id": 4, "title": "Navy / L", "options": {"color": "Navy", "size": "L"}},
        ]
        selected = filter_variants(
            variants,
            colors=["Black", "Navy"],
            sizes=["M", "L"],
            price_cents=2699,
        )
        ids = {item["id"] for item in selected}
        self.assertEqual(ids, {1, 4})
        self.assertTrue(all(item["price"] == 2699 for item in selected))

    def test_build_product_payload(self) -> None:
        config = PrintifyConfig(shop_id=1, print_provider_id=99, blueprint_id=706)
        listing = {
            "title": "Test Shirt",
            "description": "Desc",
            "tags": ["recovery shirt"],
            "price_usd": 26.99,
        }
        variants = [{"id": 10, "price": 2699, "is_enabled": True}]
        payload = build_product_payload(listing, config=config, image_id="img1", variants=variants)
        self.assertEqual(payload["blueprint_id"], 706)
        self.assertEqual(payload["print_provider_id"], 99)
        self.assertEqual(payload["print_areas"][0]["placeholders"][0]["images"][0]["id"], "img1")

    def test_load_listing_package(self) -> None:
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
            listing = load_listing_package(package)
            self.assertEqual(listing["listing_number"], 3)
            self.assertTrue(listing["print_file"].endswith("01-printify-print.png"))

    def test_push_dry_run(self) -> None:
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
            config = PrintifyConfig(shop_id=111, print_provider_id=99)
            workflow = PrintifyWorkflow(config, queue_path=Path(tmp) / "queue.json")
            result = workflow.push_package(package, dry_run=True)
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["action"], "create_draft")
            self.assertIn("printify wait", result["next_step"])

    def test_push_requires_shop_and_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "listing-03"
            images = package / "images"
            images.mkdir(parents=True)
            (images / "01-printify-print.png").write_bytes(b"img")
            (package / "listing.json").write_text(
                json.dumps({"title": "X", "description": "Y", "tags": [], "price_usd": 26.99}),
                encoding="utf-8",
            )
            workflow = PrintifyWorkflow(PrintifyConfig(), queue_path=Path(tmp) / "q.json")
            # dry-run reports missing config instead of raising
            preview = workflow.push_package(package, dry_run=True)
            self.assertIn("shop_id", preview["missing_config"])
            with self.assertRaises(PrintifyError):
                workflow.push_package(package, dry_run=False)

    def test_mark_submitted_and_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            save_queue(
                {
                    "items": [
                        {
                            "id": "abc",
                            "title": "Shirt",
                            "status": "awaiting_human_submit",
                        }
                    ]
                },
                queue_path,
            )
            workflow = PrintifyWorkflow(
                PrintifyConfig(shop_id=1, print_provider_id=1),
                queue_path=queue_path,
            )
            self.assertEqual(len(workflow.pending()), 1)
            workflow.mark_submitted("abc")
            self.assertEqual(len(workflow.pending()), 0)
            queue = load_queue(queue_path)
            self.assertEqual(queue["items"][0]["status"], "submitted_by_human")

    def test_push_package_live_mocked(self) -> None:
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
            client = MagicMock()
            client.upload_image.return_value = {"id": "img-1"}
            client.variants.return_value = [
                {"id": 10, "title": "Black / M", "options": {"color": "Black", "size": "M"}},
            ]
            client.create_product.return_value = {"id": "prod-99"}
            config = PrintifyConfig(
                shop_id=5,
                print_provider_id=9,
                enabled_colors=["Black"],
                enabled_sizes=["M"],
            )
            workflow = PrintifyWorkflow(
                config,
                client=client,
                queue_path=Path(tmp) / "queue.json",
            )
            result = workflow.push_package(package, dry_run=False)
            self.assertTrue(result["created"])
            self.assertEqual(result["product_id"], "prod-99")
            self.assertEqual(result["status"], "awaiting_human_submit")
            self.assertEqual(len(workflow.pending()), 1)
            client.create_product.assert_called_once()

    def test_auto_publish_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "listing-03"
            images = package / "images"
            images.mkdir(parents=True)
            (images / "01-printify-print.png").write_bytes(b"img")
            (package / "listing.json").write_text(
                json.dumps({"title": "X", "description": "Y", "tags": [], "price_usd": 26.99}),
                encoding="utf-8",
            )
            workflow = PrintifyWorkflow(
                PrintifyConfig(shop_id=1, print_provider_id=1, auto_publish=True),
                queue_path=Path(tmp) / "q.json",
            )
            with self.assertRaises(PrintifyError):
                workflow.push_package(package, dry_run=False)


if __name__ == "__main__":
    unittest.main()
