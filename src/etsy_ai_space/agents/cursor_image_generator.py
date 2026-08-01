"""Agent-facing image generation helpers for the Etsy AI Space.

The Python code does not generate images itself; it prepares prompts and
attaches assets that the Cursor agent creates via the GenerateImage tool.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ..db import StoreDatabase, default_db_path


def default_images_dir() -> Path:
    return Path.cwd() / "etsy_ai_space" / "exports" / "images"


def list_pending_image_jobs(
    db: StoreDatabase,
    *,
    status: str | None = "approved_for_export",
    include_needs_revision: bool = False,
) -> list[dict[str, Any]]:
    """Return drafts that have an image prompt but no image path yet."""
    statuses = [status] if status else []
    if include_needs_revision and status != "needs_revision":
        statuses.append("needs_revision")

    drafts: list[dict[str, Any]] = []
    for target_status in statuses:
        drafts.extend(db.listing_drafts(status=target_status))

    pending: list[dict[str, Any]] = []
    for draft in drafts:
        if draft.get("image_prompt") and not draft.get("image_path"):
            pending.append(
                {
                    "id": draft["id"],
                    "title": draft["title"],
                    "concept_name": draft.get("taxonomy_hint", ""),
                    "status": draft.get("status"),
                    "original_prompt": draft["image_prompt"],
                    "cursor_prompt": prepare_image_prompt(draft),
                }
            )
    return pending


def prepare_image_prompt(draft_row: dict[str, Any]) -> str:
    """Rewrite a Midjourney-style prompt into a GenerateImage-friendly description."""
    if draft_row.get("cursor_image_prompt"):
        return draft_row["cursor_image_prompt"].strip()

    original = draft_row.get("image_prompt", "")

    cleaned = re.sub(r"\s*--[a-zA-Z0-9]+\s+[\w:]+\s*", " ", original)
    cleaned = re.sub(r"\s*--[a-zA-Z0-9]+\s*", " ", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        cleaned = "A flat, print-ready t-shirt graphic on a transparent background"

    if "transparent background" not in cleaned.lower():
        cleaned += ", transparent background"
    if "print-ready" not in cleaned.lower() and "flat" not in cleaned.lower():
        cleaned = "Print-ready flat t-shirt graphic, " + cleaned

    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def save_generated_image(
    draft_id: int,
    image_path: Path | str,
    db: StoreDatabase,
    *,
    images_dir: Path | None = None,
    force: bool = False,
) -> Path:
    """Copy an agent-generated image into the export assets directory and update DB."""
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    dest_dir = images_dir or default_images_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_name = f"draft-{draft_id}{image_path.suffix}"
    dest_path = dest_dir / dest_name

    if dest_path.exists() and not force:
        raise FileExistsError(
            f"Image already exists at {dest_path}; use force=True to overwrite"
        )

    shutil.copy2(image_path, dest_path)

    with db.connection() as conn:
        conn.execute(
            "UPDATE listing_drafts SET image_path = ? WHERE id = ?",
            (str(dest_path), draft_id),
        )

    return dest_path
