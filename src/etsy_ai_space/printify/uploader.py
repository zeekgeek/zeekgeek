"""Publish approved listing drafts to Etsy via Printify (upload → create → publish).

Mirrors the WF3 step from common Make/n8n Printify automations:
  1. Upload artwork to Printify media library
  2. Create a product on a blueprint + print provider
  3. Optionally publish to the connected Etsy shop

Safety defaults match the rest of etsy_ai_space:
  - require_manual_upload=true blocks --publish unless --force-publish
  - daily_upload_cap limits how many products can be created per day
  - Without --publish, products are created in Printify only (review there)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..db import StoreDatabase, default_db_path
from ..pipeline.state_tracker import SwarmStateTracker
from ..scraper.browserclaw_uploader import (
    UPLOADABLE_STATUSES,
    count_uploads_today,
    list_upload_jobs,
    load_package_as_job,
)
from .client import PrintifyClient, PrintifyError

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG = Path.cwd() / "etsy_ai_space" / "autopilot.yaml"

# Gildan 5000 Unisex Heavy Cotton Tee is Printify blueprint 6 in most catalogs.
# Provider/color choices are merchant-specific — override in autopilot.yaml.
DEFAULT_BLUEPRINT_ID = 6
DEFAULT_PRINT_PROVIDER_ID = 99
DEFAULT_COLORS = ("Black", "White", "Navy", "Sport Grey", "Charcoal")


@dataclass
class ProductTypeConfig:
    key: str = "tshirt"
    blueprint_id: int = DEFAULT_BLUEPRINT_ID
    print_provider_id: int = DEFAULT_PRINT_PROVIDER_ID
    colors: list[str] = field(default_factory=lambda: list(DEFAULT_COLORS))
    position: str = "front"


@dataclass
class PrintifyConfig:
    require_manual_upload: bool = True
    daily_upload_cap: int = 5
    shop_id: int | None = None
    product_types: list[ProductTypeConfig] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> PrintifyConfig:
        config_path = path or DEFAULT_CONFIG
        raw: dict[str, Any] = {}
        if config_path.exists():
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                raw = loaded

        printify_raw = raw.get("printify") if isinstance(raw.get("printify"), dict) else {}
        shop_env = os.environ.get("PRINTIFY_SHOP_ID", "").strip()
        shop_id: int | None = None
        if shop_env:
            shop_id = int(shop_env)
        elif printify_raw.get("shop_id") not in (None, ""):
            shop_id = int(printify_raw["shop_id"])

        product_types: list[ProductTypeConfig] = []
        raw_types = printify_raw.get("product_types")
        if isinstance(raw_types, list) and raw_types:
            for item in raw_types:
                if not isinstance(item, dict):
                    continue
                colors = item.get("colors")
                product_types.append(
                    ProductTypeConfig(
                        key=str(item.get("key") or "tshirt"),
                        blueprint_id=int(item.get("blueprint_id", DEFAULT_BLUEPRINT_ID)),
                        print_provider_id=int(
                            item.get("print_provider_id", DEFAULT_PRINT_PROVIDER_ID)
                        ),
                        colors=[str(c) for c in colors] if isinstance(colors, list) else list(DEFAULT_COLORS),
                        position=str(item.get("position") or "front"),
                    )
                )
        else:
            product_types.append(
                ProductTypeConfig(
                    blueprint_id=int(printify_raw.get("blueprint_id", DEFAULT_BLUEPRINT_ID)),
                    print_provider_id=int(
                        printify_raw.get("print_provider_id", DEFAULT_PRINT_PROVIDER_ID)
                    ),
                    colors=[
                        str(c)
                        for c in (
                            printify_raw.get("colors")
                            if isinstance(printify_raw.get("colors"), list)
                            else DEFAULT_COLORS
                        )
                    ],
                    position=str(printify_raw.get("position") or "front"),
                )
            )

        return cls(
            require_manual_upload=bool(raw.get("require_manual_upload", True)),
            daily_upload_cap=int(raw.get("daily_upload_cap", 5)),
            shop_id=shop_id,
            product_types=product_types,
        )


def price_to_cents(price: Any) -> int:
    """Convert a dollar price (float/str) to Printify's integer cents."""
    try:
        value = float(price)
    except (TypeError, ValueError) as exc:
        raise PrintifyError(f"Invalid price: {price!r}") from exc
    if value <= 0:
        raise PrintifyError(f"Price must be positive: {price!r}")
    return int(round(value * 100))


def _variant_color(variant: dict[str, Any]) -> str:
    options = variant.get("options")
    if isinstance(options, dict):
        color = options.get("color") or options.get("Color")
        if color:
            return str(color)
    title = str(variant.get("title") or "")
    # Titles are often "Black / L"
    return title.split("/")[0].strip()


def select_variants(
    variants: list[dict[str, Any]],
    *,
    colors: list[str] | None,
    price_cents: int,
) -> list[dict[str, Any]]:
    """Pick enabled variants for product create, filtered by preferred colors when possible."""
    preferred = {c.lower() for c in (colors or []) if c}
    selected: list[dict[str, Any]] = []
    for variant in variants:
        variant_id = variant.get("id")
        if variant_id is None:
            continue
        color = _variant_color(variant)
        if preferred and color.lower() not in preferred:
            continue
        selected.append(
            {
                "id": int(variant_id),
                "price": price_cents,
                "is_enabled": True,
            }
        )
    if not selected and preferred:
        # Fall back to all variants if color filter matched nothing (catalog drift).
        LOGGER.warning(
            "No variants matched colors %s; enabling all available variants",
            sorted(preferred),
        )
        for variant in variants:
            variant_id = variant.get("id")
            if variant_id is None:
                continue
            selected.append(
                {
                    "id": int(variant_id),
                    "price": price_cents,
                    "is_enabled": True,
                }
            )
    if not selected:
        raise PrintifyError("No Printify variants available for this blueprint/provider")
    return selected


def build_product_payload(
    *,
    title: str,
    description: str,
    tags: list[str],
    blueprint_id: int,
    print_provider_id: int,
    variants: list[dict[str, Any]],
    image_id: str,
    position: str = "front",
) -> dict[str, Any]:
    variant_ids = [int(v["id"]) for v in variants]
    clean_tags = [str(t).strip() for t in tags if str(t).strip()][:13]
    return {
        "title": title[:100],
        "description": description,
        "blueprint_id": blueprint_id,
        "print_provider_id": print_provider_id,
        "variants": variants,
        "print_areas": [
            {
                "variant_ids": variant_ids,
                "placeholders": [
                    {
                        "position": position,
                        "images": [
                            {
                                "id": image_id,
                                "x": 0.5,
                                "y": 0.5,
                                "scale": 1,
                                "angle": 0,
                            }
                        ],
                    }
                ],
            }
        ],
        "tags": clean_tags,
    }


def mark_draft_printify(
    db: StoreDatabase,
    draft_id: int,
    *,
    published: bool,
    product_ids: list[str],
    shop_id: int,
) -> None:
    status = "etsy_published" if published else "etsy_draft"
    meta = {
        "uploaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "published": published,
        "via": "printify",
        "printify_shop_id": shop_id,
        "printify_product_ids": product_ids,
    }
    with db.connection() as conn:
        conn.execute(
            "UPDATE listing_drafts SET status = ?, export_json = ? WHERE id = ?",
            (status, json.dumps(meta), draft_id),
        )


def resolve_shop_id(client: PrintifyClient, config: PrintifyConfig) -> int:
    if config.shop_id is not None:
        return int(config.shop_id)
    shops = client.list_shops()
    if not shops:
        raise PrintifyError(
            "No Printify shops found. Connect an Etsy shop in Printify, then set "
            "printify.shop_id or PRINTIFY_SHOP_ID."
        )
    if len(shops) == 1:
        return int(shops[0]["id"])
    summary = ", ".join(f"{s.get('id')}={s.get('title')!r}" for s in shops)
    raise PrintifyError(
        f"Multiple Printify shops found ({summary}). Set printify.shop_id in "
        "autopilot.yaml or PRINTIFY_SHOP_ID."
    )


def publish_job_via_printify(
    job: dict[str, Any],
    *,
    client: PrintifyClient,
    config: PrintifyConfig,
    shop_id: int,
    publish: bool,
) -> dict[str, Any]:
    """Upload one listing job to Printify for each configured product type."""
    image_path = Path(str(job.get("image_path") or ""))
    if not image_path.exists():
        raise PrintifyError(f"Draft {job.get('id')} has no image_path on disk")

    price_cents = price_to_cents(job.get("price") or job.get("price_usd") or 24.99)
    upload = client.upload_image_file(image_path)
    image_id = str(upload["id"])

    created: list[dict[str, Any]] = []
    for product_type in config.product_types:
        variants_raw = client.list_variants(
            product_type.blueprint_id,
            product_type.print_provider_id,
        )
        variants = select_variants(
            variants_raw,
            colors=product_type.colors,
            price_cents=price_cents,
        )
        payload = build_product_payload(
            title=str(job["title"]),
            description=str(job.get("description") or ""),
            tags=list(job.get("tags") or []),
            blueprint_id=product_type.blueprint_id,
            print_provider_id=product_type.print_provider_id,
            variants=variants,
            image_id=image_id,
            position=product_type.position,
        )
        product = client.create_product(shop_id, payload)
        product_id = str(product["id"])
        publish_result: dict[str, Any] | None = None
        if publish:
            publish_result = client.publish_product(shop_id, product_id)
        created.append(
            {
                "product_type": product_type.key,
                "product_id": product_id,
                "blueprint_id": product_type.blueprint_id,
                "print_provider_id": product_type.print_provider_id,
                "variant_count": len(variants),
                "published": publish,
                "publish_result": publish_result or {},
            }
        )
    return {
        "draft_id": job.get("id"),
        "title": job.get("title"),
        "image_id": image_id,
        "shop_id": shop_id,
        "products": created,
        "published": publish,
    }


def run_printify_upload(
    db: StoreDatabase,
    *,
    config: PrintifyConfig,
    client: PrintifyClient | None = None,
    draft_ids: list[int] | None = None,
    package: Path | None = None,
    limit: int | None = None,
    publish: bool = False,
    force_publish: bool = False,
    dry_run: bool = False,
    tracker: SwarmStateTracker | None = None,
) -> dict[str, Any]:
    """Queue and optionally publish listing drafts through Printify."""
    if publish and config.require_manual_upload and not force_publish:
        raise RuntimeError(
            "autopilot.yaml has require_manual_upload=true. "
            "Refusing --publish. Create products only (default), set "
            "require_manual_upload=false, or pass --force-publish."
        )

    jobs: list[dict[str, Any]] = []
    if package is not None:
        jobs.append(load_package_as_job(package))
    else:
        jobs = list_upload_jobs(db, draft_ids=draft_ids)

    jobs = [j for j in jobs if j.get("has_image") or (j.get("image_path") and Path(str(j["image_path"])).exists())]
    if limit is not None:
        jobs = jobs[: max(0, limit)]

    already = count_uploads_today(db)
    remaining = max(0, config.daily_upload_cap - already)
    if not dry_run and remaining <= 0:
        raise RuntimeError(
            f"daily_upload_cap reached ({config.daily_upload_cap}). Try again tomorrow."
        )
    if not dry_run and len(jobs) > remaining:
        LOGGER.warning(
            "Truncating queue from %d to %d (daily_upload_cap)",
            len(jobs),
            remaining,
        )
        jobs = jobs[:remaining]

    preview = [
        {
            "id": j.get("id"),
            "title": j.get("title"),
            "price": j.get("price"),
            "image_path": j.get("image_path"),
            "product_types": [p.key for p in config.product_types],
        }
        for j in jobs
    ]
    if dry_run:
        return {
            "dry_run": True,
            "publish": publish,
            "uploads_today": already,
            "daily_upload_cap": config.daily_upload_cap,
            "shop_id": config.shop_id,
            "queue": preview,
        }

    if not jobs:
        return {"uploaded": 0, "results": [], "message": "No uploadable drafts with images"}

    active_client = client or PrintifyClient()
    shop_id = resolve_shop_id(active_client, config)
    state = tracker or SwarmStateTracker()
    results: list[dict[str, Any]] = []

    for job in jobs:
        state.log(f"Printify upload: {job.get('title')!r} (draft={job.get('id')})")
        result = publish_job_via_printify(
            job,
            client=active_client,
            config=config,
            shop_id=shop_id,
            publish=publish,
        )
        draft_id = job.get("id")
        # Package jobs use listing_number as id — only mark real SQLite drafts.
        if isinstance(draft_id, int) and job.get("status") in UPLOADABLE_STATUSES:
            mark_draft_printify(
                db,
                draft_id,
                published=publish,
                product_ids=[p["product_id"] for p in result["products"]],
                shop_id=shop_id,
            )
        results.append(result)
        state.log(
            f"Printify {'published' if publish else 'created'} "
            f"{len(result['products'])} product(s) for draft={draft_id}"
        )

    return {
        "uploaded": len(results),
        "published": publish,
        "shop_id": shop_id,
        "uploads_today": count_uploads_today(db),
        "results": results,
    }


async def _cli(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db or default_db_path())
    config = PrintifyConfig.load(args.config)

    if getattr(args, "list_shops", False):
        client = PrintifyClient()
        shops = client.list_shops()
        print(json.dumps(shops, indent=2))
        return 0

    if getattr(args, "list_providers", None) is not None:
        client = PrintifyClient()
        providers = client.list_blueprint_providers(int(args.list_providers))
        print(json.dumps(providers, indent=2))
        return 0

    if args.list:
        jobs = list_upload_jobs(
            db,
            draft_ids=[int(x) for x in args.draft_id] if args.draft_id else None,
        )
        print(json.dumps(jobs, indent=2))
        return 0

    draft_ids = [int(x) for x in args.draft_id] if args.draft_id else None
    try:
        result = run_printify_upload(
            db,
            config=config,
            draft_ids=draft_ids,
            package=args.package,
            limit=args.limit,
            publish=bool(args.publish),
            force_publish=bool(args.force_publish),
            dry_run=bool(args.dry_run),
        )
    except (PrintifyError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload listing drafts via Printify → Etsy")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--list", action="store_true", help="List uploadable drafts")
    parser.add_argument("--list-shops", action="store_true", help="List Printify shops for token")
    parser.add_argument(
        "--list-providers",
        type=int,
        metavar="BLUEPRINT_ID",
        default=None,
        help="List print providers for a blueprint id",
    )
    parser.add_argument("--draft-id", action="append", help="Draft id to upload (repeatable)")
    parser.add_argument("--package", type=Path, default=None, help="Listing package folder")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish created products to the connected Etsy shop",
    )
    parser.add_argument(
        "--force-publish",
        action="store_true",
        help="Allow --publish even when require_manual_upload=true",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview queue only")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(__import__("asyncio").run(_cli(args)))


# Re-export for typing clarity in tests
__all__ = [
    "PrintifyConfig",
    "ProductTypeConfig",
    "UPLOADABLE_STATUSES",
    "build_product_payload",
    "mark_draft_printify",
    "price_to_cents",
    "publish_job_via_printify",
    "run_printify_upload",
    "select_variants",
    "resolve_shop_id",
]
