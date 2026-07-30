"""Phase 4 — export bundles for design packs and manual Etsy upload."""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from ..db import StoreDatabase


def _shirt_text_from_prompt(image_prompt: str) -> str:
    match = re.search(
        r"SHIRT TEXT \(type this exactly in Canva\):\n(.*?)\n\n---",
        image_prompt or "",
        flags=re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _write_csv(path: Path, drafts: list[dict]) -> None:
    fieldnames = [
        "title",
        "description",
        "tags",
        "price",
        "image_prompt",
        "image_path",
        "taxonomy_hint",
        "status",
        "shirt_text",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
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
                    "image_path": draft.get("image_path") or "",
                    "taxonomy_hint": draft.get("taxonomy_hint") or "",
                    "status": draft.get("status") or "",
                    "shirt_text": _shirt_text_from_prompt(str(draft.get("image_prompt") or "")),
                }
            )


def export_design_pack(
    db: StoreDatabase,
    out_dir: Path,
    *,
    statuses: tuple[str, ...] = ("pending_review", "approved_for_export"),
) -> dict[str, str]:
    """Write a design pack for Canva without marking drafts as uploaded/exported."""
    out_dir.mkdir(parents=True, exist_ok=True)
    drafts: list[dict] = []
    seen: set[int] = set()
    for status in statuses:
        for draft in db.listing_drafts(status=status):
            draft_id = int(draft.get("id") or 0)
            if draft_id in seen:
                continue
            seen.add(draft_id)
            drafts.append(draft)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"design-pack-{stamp}.json"
    csv_path = out_dir / f"design-pack-{stamp}.csv"
    md_path = out_dir / f"design-pack-{stamp}.md"

    listings = []
    for draft in drafts:
        prompt = str(draft.get("image_prompt") or "")
        listings.append(
            {
                **draft,
                "shirt_text": _shirt_text_from_prompt(prompt),
            }
        )

    bundle = {
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pack_type": "design_pack",
        "count": len(listings),
        "listings": listings,
        "workflow": [
            "Open each listing's image_prompt CANVA section.",
            "Create a 4500×5400 transparent PNG in Canva.",
            "Upload art to Printful/Printify and generate mockups.",
            "When ready to sell: python3 -m etsy_ai_space approve && python3 -m etsy_ai_space export",
            "Upload the listing-bundle JSON/CSV fields manually in Etsy Seller Manager.",
        ],
        "notes": (
            "This pack does NOT mark drafts as exported. Etsy publish stays manual "
            "while your shop is new / unverified."
        ),
    }
    json_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    _write_csv(csv_path, listings)

    lines = [
        "# Design pack — Canva workflow",
        "",
        f"Generated: {bundle['exported_at']}",
        f"Drafts: {len(listings)}",
        "",
        "Etsy upload is still manual. Use this pack to build shirt art.",
        "",
    ]
    for index, draft in enumerate(listings, start=1):
        lines.extend(
            [
                f"## {index}. {draft.get('title')}",
                "",
                f"- Status: `{draft.get('status')}`",
                f"- Price: `${draft.get('price')}`",
                f"- Tags: {', '.join(draft.get('tags') or [])}",
                "",
                "### Shirt text (type in Canva)",
                "",
                "```",
                draft.get("shirt_text") or "(see image_prompt)",
                "```",
                "",
                "### Full art brief",
                "",
                "```",
                str(draft.get("image_prompt") or ""),
                "```",
                "",
            ]
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "markdown": str(md_path),
        "count": str(len(listings)),
    }


def export_pending_drafts(db: StoreDatabase, out_dir: Path) -> dict[str, str]:
    """Write JSON + CSV bundles for approved drafts and mark them exported."""
    out_dir.mkdir(parents=True, exist_ok=True)
    drafts = db.listing_drafts(status="approved_for_export")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"listing-bundle-{stamp}.json"
    csv_path = out_dir / f"listing-bundle-{stamp}.csv"

    bundle = {
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pack_type": "listing_bundle",
        "count": len(drafts),
        "listings": drafts,
        "upload_notes": (
            "Manual upload recommended for new shops. Attach image files separately using image_path."
        ),
    }
    json_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    _write_csv(csv_path, drafts)

    with db.connection() as conn:
        for draft in drafts:
            conn.execute(
                "UPDATE listing_drafts SET export_json = ?, status = ? WHERE id = ?",
                (str(json_path), "exported", draft["id"]),
            )

    return {"json": str(json_path), "csv": str(csv_path), "count": str(len(drafts))}
