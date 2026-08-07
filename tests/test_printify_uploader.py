"""Tests for Printify upload helpers (mocked HTTP)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from etsy_ai_space.db import StoreDatabase
from etsy_ai_space.models import ListingDraft
from etsy_ai_space.printify.client import PrintifyClient, PrintifyError
from etsy_ai_space.printify.uploader import (
    PrintifyConfig,
    ProductTypeConfig,
    build_product_payload,
    mark_draft_printify,
    price_to_cents,
    run_printify_upload,
    select_variants,
)


class FakePrintifyClient:
    """In-memory stand-in for PrintifyClient."""

    def __init__(self) -> None:
        self.uploads: list[Path] = []
        self.created: list[dict[str, Any]] = []
        self.published: list[str] = []
        self._product_seq = 0

    def list_shops(self) -> list[dict[str, Any]]:
        return [{"id": 4242, "title": "Demo Etsy Shop"}]

    def list_variants(self, blueprint_id: int, print_provider_id: int) -> list[dict[str, Any]]:
        assert blueprint_id == 6
        assert print_provider_id == 99
        return [
            {"id": 101, "title": "Black / S", "options": {"color": "Black", "size": "S"}},
            {"id": 102, "title": "Black / M", "options": {"color": "Black", "size": "M"}},
            {"id": 201, "title": "Red / M", "options": {"color": "Red", "size": "M"}},
        ]

    def upload_image_file(self, path: Path, *, file_name: str | None = None) -> dict[str, Any]:
        self.uploads.append(Path(path))
        return {"id": "img-abc", "file_name": file_name or Path(path).name}

    def create_product(self, shop_id: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        self._product_seq += 1
        product_id = f"prod-{self._product_seq}"
        self.created.append({"shop_id": shop_id, "payload": payload, "id": product_id})
        return {"id": product_id, "title": payload.get("title")}

    def publish_product(self, shop_id: int | str, product_id: str, **kwargs: Any) -> dict[str, Any]:
        self.published.append(str(product_id))
        return {}


class PrintifyUploaderTests(unittest.TestCase):
    def test_price_to_cents(self) -> None:
        self.assertEqual(price_to_cents(26.99), 2699)
        self.assertEqual(price_to_cents("24.99"), 2499)
        with self.assertRaises(PrintifyError):
            price_to_cents(0)

    def test_select_variants_filters_colors(self) -> None:
        variants = [
            {"id": 1, "options": {"color": "Black"}},
            {"id": 2, "options": {"color": "Red"}},
            {"id": 3, "options": {"color": "Navy"}},
        ]
        selected = select_variants(variants, colors=["Black", "Navy"], price_cents=2500)
        self.assertEqual([v["id"] for v in selected], [1, 3])
        self.assertTrue(all(v["price"] == 2500 for v in selected))

    def test_build_product_payload(self) -> None:
        variants = [{"id": 10, "price": 2500, "is_enabled": True}]
        payload = build_product_payload(
            title="We Do Recover Tee",
            description="Soft unisex recovery shirt.",
            tags=["recovery shirt", "sobriety gift"],
            blueprint_id=6,
            print_provider_id=99,
            variants=variants,
            image_id="img-1",
        )
        self.assertEqual(payload["blueprint_id"], 6)
        self.assertEqual(payload["print_areas"][0]["placeholders"][0]["images"][0]["id"], "img-1")
        self.assertEqual(payload["tags"], ["recovery shirt", "sobriety gift"])

    def test_config_loads_printify_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autopilot.yaml"
            path.write_text(
                "\n".join(
                    [
                        "require_manual_upload: true",
                        "daily_upload_cap: 3",
                        "printify:",
                        "  shop_id: 99",
                        "  product_types:",
                        "    - key: tshirt",
                        "      blueprint_id: 6",
                        "      print_provider_id: 55",
                        "      colors: [Black]",
                    ]
                ),
                encoding="utf-8",
            )
            config = PrintifyConfig.load(path)
            self.assertTrue(config.require_manual_upload)
            self.assertEqual(config.daily_upload_cap, 3)
            self.assertEqual(config.shop_id, 99)
            self.assertEqual(len(config.product_types), 1)
            self.assertEqual(config.product_types[0].print_provider_id, 55)
            self.assertEqual(config.product_types[0].colors, ["Black"])

    def test_client_requires_token(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(PrintifyError):
                PrintifyClient(token="")

    def test_dry_run_and_create_without_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            image = Path(tmp) / "design.png"
            image.write_bytes(b"fakepng")
            draft = db.save_listing_draft(
                ListingDraft(
                    title="Ready Tee",
                    description="Specific recovery description for testing.",
                    tags=["recovery shirt"],
                    price=26.99,
                    image_prompt="phoenix",
                    image_path=str(image),
                    status="approved_for_export",
                )
            )
            config = PrintifyConfig(
                require_manual_upload=True,
                daily_upload_cap=5,
                shop_id=4242,
                product_types=[
                    ProductTypeConfig(
                        key="tshirt",
                        blueprint_id=6,
                        print_provider_id=99,
                        colors=["Black"],
                    )
                ],
            )
            dry = run_printify_upload(db, config=config, dry_run=True)
            self.assertTrue(dry["dry_run"])
            self.assertEqual(len(dry["queue"]), 1)

            with self.assertRaises(RuntimeError):
                run_printify_upload(
                    db,
                    config=config,
                    client=FakePrintifyClient(),
                    publish=True,
                    force_publish=False,
                )

            fake = FakePrintifyClient()
            result = run_printify_upload(
                db,
                config=config,
                client=fake,
                draft_ids=[draft.id],
                publish=False,
            )
            self.assertEqual(result["uploaded"], 1)
            self.assertFalse(result["published"])
            self.assertEqual(len(fake.created), 1)
            self.assertEqual(fake.published, [])
            self.assertEqual(fake.created[0]["payload"]["variants"][0]["price"], 2699)
            rows = db.listing_drafts(status="etsy_draft")
            self.assertEqual(len(rows), 1)
            meta = json.loads(rows[0]["export_json"])
            self.assertEqual(meta["via"], "printify")
            self.assertFalse(meta["published"])

    def test_force_publish_marks_published(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            image = Path(tmp) / "design.png"
            image.write_bytes(b"fakepng")
            draft = db.save_listing_draft(
                ListingDraft(
                    title="Publish Tee",
                    description="Specific recovery description for testing.",
                    tags=["recovery shirt"],
                    price=24.99,
                    image_prompt="phoenix",
                    image_path=str(image),
                    status="approved_for_export",
                )
            )
            config = PrintifyConfig(
                require_manual_upload=True,
                daily_upload_cap=5,
                shop_id=4242,
                product_types=[ProductTypeConfig(colors=["Black"])],
            )
            fake = FakePrintifyClient()
            result = run_printify_upload(
                db,
                config=config,
                client=fake,
                draft_ids=[draft.id],
                publish=True,
                force_publish=True,
            )
            self.assertTrue(result["published"])
            self.assertEqual(fake.published, ["prod-1"])
            rows = db.listing_drafts(status="etsy_published")
            self.assertEqual(len(rows), 1)

    def test_mark_draft_printify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            draft = db.save_listing_draft(
                ListingDraft(
                    title="Ready",
                    description="Specific recovery description for testing.",
                    tags=["recovery shirt"],
                    price=26.99,
                    image_prompt="phoenix",
                    status="approved_for_export",
                )
            )
            mark_draft_printify(
                db,
                draft.id,
                published=False,
                product_ids=["abc"],
                shop_id=1,
            )
            rows = db.listing_drafts(status="etsy_draft")
            meta = json.loads(rows[0]["export_json"])
            self.assertEqual(meta["printify_product_ids"], ["abc"])


if __name__ == "__main__":
    unittest.main()
