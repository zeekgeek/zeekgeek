"""Tests for BrowserClaw listing upload helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from etsy_ai_space.db import StoreDatabase
from etsy_ai_space.models import ListingDraft
from etsy_ai_space.scraper.browserclaw_uploader import (
    UploadConfig,
    count_uploads_today,
    list_upload_jobs,
    load_package_as_job,
    mark_draft_uploaded,
    run_browserclaw_upload,
)


class BrowserclawUploaderTests(unittest.IsolatedAsyncioTestCase):
    def test_list_upload_jobs_requires_exportable_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            image = Path(tmp) / "hero.png"
            image.write_bytes(b"fake")
            db.save_listing_draft(
                ListingDraft(
                    title="Pending",
                    description="Specific recovery description for testing.",
                    tags=["recovery shirt"],
                    price=26.99,
                    image_prompt="phoenix",
                    image_path=str(image),
                    status="pending_review",
                )
            )
            db.save_listing_draft(
                ListingDraft(
                    title="Ready",
                    description="Specific recovery description for testing.",
                    tags=["recovery shirt"],
                    price=26.99,
                    image_prompt="phoenix",
                    image_path=str(image),
                    status="approved_for_export",
                )
            )
            jobs = list_upload_jobs(db)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["title"], "Ready")
            self.assertTrue(jobs[0]["has_image"])

    def test_upload_config_loads_caps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autopilot.yaml"
            path.write_text(
                "require_manual_upload: true\ndaily_upload_cap: 3\n",
                encoding="utf-8",
            )
            config = UploadConfig.load(path)
            self.assertTrue(config.require_manual_upload)
            self.assertEqual(config.daily_upload_cap, 3)

    def test_mark_and_count_uploads_today(self) -> None:
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
            self.assertEqual(count_uploads_today(db), 0)
            mark_draft_uploaded(db, draft.id, published=False)
            self.assertEqual(count_uploads_today(db), 1)
            rows = db.listing_drafts(status="etsy_draft")
            self.assertEqual(len(rows), 1)
            meta = json.loads(rows[0]["export_json"])
            self.assertEqual(meta["via"], "browserclaw")
            self.assertFalse(meta["published"])

    def test_load_package_as_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "listing-02"
            images = package / "images"
            images.mkdir(parents=True)
            (images / "01-hero-black-lifestyle.png").write_bytes(b"img")
            (package / "listing.json").write_text(
                json.dumps(
                    {
                        "listing_number": 2,
                        "title": "We Do Recover Every Day Shirt",
                        "description": "Bold phoenix recovery tee.",
                        "tags": ["recovery shirt", "sobriety tee"],
                        "price_usd": 26.99,
                    }
                ),
                encoding="utf-8",
            )
            job = load_package_as_job(package)
            self.assertEqual(job["id"], 2)
            self.assertEqual(job["price"], 26.99)
            self.assertTrue(job["has_image"])
            self.assertIn("01-hero-black-lifestyle.png", job["image_path"])

    async def test_dry_run_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            image = Path(tmp) / "hero.png"
            image.write_bytes(b"fake")
            db.save_listing_draft(
                ListingDraft(
                    title="Ready",
                    description="Specific recovery description for testing.",
                    tags=["recovery shirt"],
                    price=26.99,
                    image_prompt="phoenix",
                    image_path=str(image),
                    status="exported",
                )
            )
            config = Path(tmp) / "autopilot.yaml"
            config.write_text(
                "require_manual_upload: true\ndaily_upload_cap: 5\n",
                encoding="utf-8",
            )
            result = await run_browserclaw_upload(
                db,
                config_path=config,
                dry_run=True,
                publish=False,
            )
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["queued"], 1)
            self.assertEqual(result["jobs"][0]["action"], "save_draft")

    async def test_publish_blocked_when_manual_gate_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            config = Path(tmp) / "autopilot.yaml"
            config.write_text(
                "require_manual_upload: true\ndaily_upload_cap: 5\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                await run_browserclaw_upload(
                    db,
                    config_path=config,
                    publish=True,
                    force_publish=False,
                    dry_run=False,
                )

    async def test_daily_cap_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            image = Path(tmp) / "hero.png"
            image.write_bytes(b"fake")
            for index in range(2):
                draft = db.save_listing_draft(
                    ListingDraft(
                        title=f"Ready {index}",
                        description="Specific recovery description for testing.",
                        tags=["recovery shirt"],
                        price=26.99,
                        image_prompt="phoenix",
                        image_path=str(image),
                        status="approved_for_export",
                    )
                )
                mark_draft_uploaded(db, draft.id, published=False)
            # One more waiting
            db.save_listing_draft(
                ListingDraft(
                    title="Waiting",
                    description="Specific recovery description for testing.",
                    tags=["recovery shirt"],
                    price=26.99,
                    image_prompt="phoenix",
                    image_path=str(image),
                    status="approved_for_export",
                )
            )
            config = Path(tmp) / "autopilot.yaml"
            config.write_text(
                "require_manual_upload: true\ndaily_upload_cap: 2\n",
                encoding="utf-8",
            )
            result = await run_browserclaw_upload(db, config_path=config, dry_run=True)
            self.assertTrue(result.get("skipped"))
            self.assertEqual(result["reason"], "daily_upload_cap")


if __name__ == "__main__":
    unittest.main()
