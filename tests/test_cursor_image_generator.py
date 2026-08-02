"""Tests for the Cursor-agent image generation helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from etsy_ai_space.agents.cursor_image_generator import (
    default_images_dir,
    list_pending_image_jobs,
    prepare_image_prompt,
    save_generated_image,
)
from etsy_ai_space.db import StoreDatabase
from etsy_ai_space.models import ListingDraft


class CursorImageGeneratorTests(unittest.TestCase):
    def test_prepare_prompt_strips_midjourney_parameters(self) -> None:
        prompt = prepare_image_prompt(
            {"image_prompt": "A cat graphic --ar 1:1 --style raw --v 6.0"}
        )
        self.assertNotIn("--ar", prompt)
        self.assertNotIn("--style", prompt)
        self.assertNotIn("--v", prompt)
        self.assertIn("cat graphic", prompt.lower())
        self.assertIn("transparent background", prompt.lower())

    def test_prepare_prompt_uses_cursor_image_prompt_when_present(self) -> None:
        prompt = prepare_image_prompt(
            {
                "image_prompt": "A cat graphic --ar 1:1",
                "cursor_image_prompt": "A custom cursor prompt for a cat tee",
            }
        )
        self.assertEqual(prompt, "A custom cursor prompt for a cat tee")

    def test_prepare_prompt_falls_back_for_empty_input(self) -> None:
        prompt = prepare_image_prompt({})
        self.assertIn("transparent background", prompt.lower())

    def test_list_pending_jobs_returns_only_drafts_without_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            db.save_listing_draft(
                ListingDraft(
                    title="Has Image",
                    description="Specific description without generic filler.",
                    tags=["retro cat shirt", "vintage tee"],
                    price=24.99,
                    image_prompt="A cat graphic",
                    cursor_image_prompt="A cat graphic for cursor",
                    image_path="/some/path.png",
                    status="approved_for_export",
                )
            )
            db.save_listing_draft(
                ListingDraft(
                    title="Needs Image",
                    description="Specific description without generic filler.",
                    tags=["retro cat shirt", "vintage tee"],
                    price=24.99,
                    image_prompt="A dog graphic",
                    cursor_image_prompt="A dog graphic for cursor",
                    status="approved_for_export",
                )
            )
            jobs = list_pending_image_jobs(db)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["title"], "Needs Image")
            self.assertEqual(jobs[0]["cursor_prompt"], "A dog graphic for cursor")

    def test_list_pending_jobs_filters_by_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            db.save_listing_draft(
                ListingDraft(
                    title="Pending Review",
                    description="Specific description without generic filler.",
                    tags=["retro cat shirt"],
                    price=24.99,
                    image_prompt="A cat graphic",
                    status="pending_review",
                )
            )
            db.save_listing_draft(
                ListingDraft(
                    title="Approved",
                    description="Specific description without generic filler.",
                    tags=["retro cat shirt"],
                    price=24.99,
                    image_prompt="A dog graphic",
                    status="approved_for_export",
                )
            )
            jobs = list_pending_image_jobs(db, status="pending_review")
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["title"], "Pending Review")

    def test_list_pending_jobs_includes_needs_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            db.save_listing_draft(
                ListingDraft(
                    title="Revision",
                    description="Specific description without generic filler.",
                    tags=["retro cat shirt"],
                    price=24.99,
                    image_prompt="A cat graphic",
                    status="needs_revision",
                )
            )
            jobs = list_pending_image_jobs(
                db, status="approved_for_export", include_needs_revision=True
            )
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["title"], "Revision")

    def test_save_generated_image_copies_and_updates_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            draft = db.save_listing_draft(
                ListingDraft(
                    title="Draft",
                    description="Specific description without generic filler.",
                    tags=["retro cat shirt"],
                    price=24.99,
                    image_prompt="A cat graphic",
                    status="approved_for_export",
                )
            )
            source_image = Path(tmp) / "generated.png"
            source_image.write_bytes(b"fake image bytes")
            images_dir = Path(tmp) / "images"

            dest = save_generated_image(draft.id, source_image, db, images_dir=images_dir)

            self.assertTrue(dest.exists())
            self.assertEqual(dest.name, f"draft-{draft.id}.png")
            rows = db.listing_drafts(status="approved_for_export")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["image_path"], str(dest))

    def test_save_generated_image_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            draft = db.save_listing_draft(
                ListingDraft(
                    title="Draft",
                    description="Specific description without generic filler.",
                    tags=["retro cat shirt"],
                    price=24.99,
                    image_prompt="A cat graphic",
                    status="approved_for_export",
                )
            )
            source_image = Path(tmp) / "generated.png"
            source_image.write_bytes(b"fake image bytes")
            images_dir = Path(tmp) / "images"
            save_generated_image(draft.id, source_image, db, images_dir=images_dir)
            with self.assertRaises(FileExistsError):
                save_generated_image(draft.id, source_image, db, images_dir=images_dir)

    def test_save_generated_image_overwrites_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            draft = db.save_listing_draft(
                ListingDraft(
                    title="Draft",
                    description="Specific description without generic filler.",
                    tags=["retro cat shirt"],
                    price=24.99,
                    image_prompt="A cat graphic",
                    status="approved_for_export",
                )
            )
            source_image = Path(tmp) / "generated.png"
            source_image.write_bytes(b"fake image bytes")
            images_dir = Path(tmp) / "images"
            save_generated_image(draft.id, source_image, db, images_dir=images_dir)
            dest = save_generated_image(
                draft.id, source_image, db, images_dir=images_dir, force=True
            )
            self.assertTrue(dest.exists())

    def test_save_generated_image_raises_for_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StoreDatabase(Path(tmp) / "store.db")
            draft = db.save_listing_draft(
                ListingDraft(
                    title="Draft",
                    description="Specific description without generic filler.",
                    tags=["retro cat shirt"],
                    price=24.99,
                    image_prompt="A cat graphic",
                    status="approved_for_export",
                )
            )
            with self.assertRaises(FileNotFoundError):
                save_generated_image(draft.id, Path(tmp) / "missing.png", db)

    def test_default_images_dir(self) -> None:
        self.assertIn("etsy_ai_space/exports/images", str(default_images_dir()))


if __name__ == "__main__":
    unittest.main()
