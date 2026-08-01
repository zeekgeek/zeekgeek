"""Phase 4 — export bundles for manual Etsy upload."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from ..db import StoreDatabase


def export_pending_drafts(db: StoreDatabase, out_dir: Path) -> dict[str, str]:
    """Write JSON + CSV bundles for approved drafts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    drafts = db.listing_drafts(status="approved_for_export")
    if not drafts:
        drafts = db.listing_drafts()

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"listing-bundle-{stamp}.json"
    csv_path = out_dir / f"listing-bundle-{stamp}.csv"

    bundle = {
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "count": len(drafts),
        "listings": drafts,
        "upload_notes": (
            "Manual upload recommended for new shops. Attach image files separately using image_path."
        ),
    }
    json_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    fieldnames = [
        "title",
        "description",
        "tags",
        "price",
        "image_prompt",
        "cursor_image_prompt",
        "image_path",
        "taxonomy_hint",
        "status",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for draft in drafts:
            writer.writerow(
                {
                    "title": draft["title"],
                    "description": draft["description"],
                    "tags": "|".join(draft.get("tags") or []),
                    "price": draft["price"],
                    "image_prompt": draft["image_prompt"],
                    "cursor_image_prompt": draft.get("cursor_image_prompt") or "",
                    "image_path": draft.get("image_path") or "",
                    "taxonomy_hint": draft.get("taxonomy_hint") or "",
                    "status": draft.get("status") or "",
                }
            )

    with db.connection() as conn:
        for draft in drafts:
            conn.execute(
                "UPDATE listing_drafts SET export_json = ?, status = ? WHERE id = ?",
                (str(json_path), "exported", draft["id"]),
            )

    return {"json": str(json_path), "csv": str(csv_path), "count": str(len(drafts))}
