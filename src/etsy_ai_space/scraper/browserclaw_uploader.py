"""Upload listing drafts to Etsy Seller Manager via BrowserClaw (CDP attach).

Default behavior saves listings as **Draft** so you can review before publish.
Pass ``--publish`` (and disable ``require_manual_upload`` or use ``--force-publish``)
to click Publish after the form is filled.

Requires an active BrowserClaw Chromium session already logged into your Etsy
seller account.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..db import StoreDatabase, default_db_path
from ..pipeline.state_tracker import SwarmStateTracker
from ..tools.delays import human_delay, micro_delay
from .browser_connect import acquire_page, connect_over_cdp, resolve_cdp_url

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG = Path.cwd() / "etsy_ai_space" / "autopilot.yaml"
CREATE_LISTING_URLS = (
    "https://www.etsy.com/your/shops/me/tools/listings/create",
    "https://www.etsy.com/your/shops/me/listing-editor/create",
)

UPLOADABLE_STATUSES = ("approved_for_export", "exported")
UPLOADED_STATUSES = ("etsy_draft", "etsy_published", "uploaded")


@dataclass
class UploadConfig:
    require_manual_upload: bool = True
    daily_upload_cap: int = 5

    @classmethod
    def load(cls, path: Path | None = None) -> UploadConfig:
        config_path = path or DEFAULT_CONFIG
        if not config_path.exists():
            return cls()
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return cls(
            require_manual_upload=bool(raw.get("require_manual_upload", True)),
            daily_upload_cap=int(raw.get("daily_upload_cap", 5)),
        )


def list_upload_jobs(
    db: StoreDatabase,
    *,
    draft_ids: list[int] | None = None,
    include_uploaded: bool = False,
) -> list[dict[str, Any]]:
    """Return drafts ready for BrowserClaw upload."""
    jobs: list[dict[str, Any]] = []
    for status in UPLOADABLE_STATUSES:
        for draft in db.listing_drafts(status=status):
            if draft_ids is not None and draft["id"] not in draft_ids:
                continue
            if not include_uploaded and draft.get("status") in UPLOADED_STATUSES:
                continue
            image_path = draft.get("image_path") or ""
            jobs.append(
                {
                    "id": draft["id"],
                    "title": draft["title"],
                    "description": draft["description"],
                    "tags": draft.get("tags") or [],
                    "price": draft.get("price"),
                    "image_path": image_path,
                    "status": draft.get("status"),
                    "has_image": bool(image_path and Path(image_path).exists()),
                    "taxonomy_hint": draft.get("taxonomy_hint") or "",
                }
            )
    # Stable order: oldest first for upload queue
    jobs.sort(key=lambda item: item["id"])
    return jobs


def count_uploads_today(db: StoreDatabase) -> int:
    """Count drafts marked uploaded/drafted/published today (UTC)."""
    today = datetime.now(UTC).date().isoformat()
    count = 0
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT status, created_at, export_json FROM listing_drafts
            WHERE status IN ('etsy_draft', 'etsy_published', 'uploaded')
            """
        ).fetchall()
    for row in rows:
        stamp = ""
        raw_meta = row["export_json"]
        if raw_meta:
            try:
                meta = json.loads(str(raw_meta))
                if isinstance(meta, dict):
                    stamp = str(meta.get("uploaded_at") or "")
            except json.JSONDecodeError:
                stamp = str(raw_meta)
        if not stamp:
            stamp = str(row["created_at"] or "")
        if stamp.startswith(today):
            count += 1
    return count


def mark_draft_uploaded(
    db: StoreDatabase,
    draft_id: int,
    *,
    published: bool,
    etsy_url: str | None = None,
) -> None:
    """Update draft status after a successful BrowserClaw upload."""
    status = "etsy_published" if published else "etsy_draft"
    meta = {
        "uploaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "published": published,
        "etsy_url": etsy_url or "",
        "via": "browserclaw",
    }
    with db.connection() as conn:
        conn.execute(
            "UPDATE listing_drafts SET status = ?, export_json = ? WHERE id = ?",
            (status, json.dumps(meta), draft_id),
        )


async def _fill_first_match(page: Any, selectors: list[str], value: str, *, label: str) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0:
                continue
            await locator.wait_for(state="visible", timeout=4000)
            await locator.click()
            await micro_delay(0.2, 0.6)
            await locator.fill("")
            await locator.type(value, delay=25)
            LOGGER.info("Filled %s via %s", label, selector)
            return True
        except Exception:
            continue
    LOGGER.warning("Could not fill %s — tried %s", label, selectors)
    return False


async def _click_first_match(page: Any, selectors: list[str], *, label: str) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0:
                continue
            await locator.wait_for(state="visible", timeout=4000)
            await locator.click()
            LOGGER.info("Clicked %s via %s", label, selector)
            return True
        except Exception:
            continue
    LOGGER.warning("Could not click %s — tried %s", label, selectors)
    return False


async def _upload_images(page: Any, image_paths: list[Path]) -> int:
    existing = [path for path in image_paths if path.exists()]
    if not existing:
        return 0
    file_selectors = [
        'input[type="file"][accept*="image"]',
        'input[type="file"]',
    ]
    for selector in file_selectors:
        locator = page.locator(selector)
        try:
            count = await locator.count()
            if count == 0:
                continue
            await locator.first.set_input_files([str(path) for path in existing])
            LOGGER.info("Uploaded %d image(s) via %s", len(existing), selector)
            await human_delay(1.5, 3.0)
            return len(existing)
        except Exception:
            continue
    LOGGER.warning("Could not find a file input for image upload")
    return 0


async def _add_tags(page: Any, tags: list[str]) -> int:
    added = 0
    tag_selectors = [
        'input[name="tags"]',
        'input[placeholder*="tag" i]',
        'input[aria-label*="tag" i]',
        '#listing-tags-input',
    ]
    for tag in tags[:13]:
        filled = False
        for selector in tag_selectors:
            locator = page.locator(selector).first
            try:
                if await locator.count() == 0:
                    continue
                await locator.click()
                await locator.fill(tag)
                await page.keyboard.press("Enter")
                await micro_delay(0.2, 0.5)
                added += 1
                filled = True
                break
            except Exception:
                continue
        if not filled:
            LOGGER.warning("Could not add tag %r", tag)
    return added


async def upload_listing_via_browserclaw(
    draft: dict[str, Any],
    *,
    cdp_url: str,
    publish: bool = False,
    reuse_browser_tab: bool = True,
    extra_images: list[Path] | None = None,
) -> dict[str, Any]:
    """Attach to BrowserClaw and create one Etsy listing from a draft dict."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install -e '.[etsy]' && playwright install chromium"
        ) from exc

    image_paths: list[Path] = []
    if draft.get("image_path"):
        image_paths.append(Path(draft["image_path"]))
    if extra_images:
        image_paths.extend(extra_images)

    async with async_playwright() as playwright:
        browser = await connect_over_cdp(playwright, cdp_url)
        _browser, page, owns_page = await acquire_page(browser, reuse_existing=reuse_browser_tab)

        opened = False
        for url in CREATE_LISTING_URLS:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await human_delay(2.0, 4.0)
                opened = True
                break
            except Exception as exc:
                LOGGER.warning("Failed to open %s: %s", url, exc)
        if not opened:
            raise RuntimeError("Could not open Etsy listing creator — is BrowserClaw logged in?")

        # Bail early if redirected to login
        if "signin" in (page.url or "").lower() or "login" in (page.url or "").lower():
            raise RuntimeError(
                "Etsy login required. Log into your seller account in BrowserClaw, then retry."
            )

        title_ok = await _fill_first_match(
            page,
            [
                'input[name="title"]',
                'textarea[name="title"]',
                'input[placeholder*="title" i]',
                'input[aria-label*="title" i]',
                '#listing-title-input',
            ],
            str(draft["title"])[:140],
            label="title",
        )
        await human_delay(0.8, 1.5)

        desc_ok = await _fill_first_match(
            page,
            [
                'textarea[name="description"]',
                'div[contenteditable="true"][aria-label*="description" i]',
                'textarea[placeholder*="description" i]',
                '#listing-description-textarea',
            ],
            str(draft["description"]),
            label="description",
        )
        await human_delay(0.8, 1.5)

        price_ok = await _fill_first_match(
            page,
            [
                'input[name="price"]',
                'input[inputmode="decimal"]',
                'input[placeholder*="price" i]',
                'input[aria-label*="price" i]',
            ],
            f"{float(draft['price']):.2f}",
            label="price",
        )
        await human_delay(0.5, 1.2)

        tags_added = await _add_tags(page, list(draft.get("tags") or []))
        images_uploaded = await _upload_images(page, image_paths)

        action = "publish" if publish else "save_draft"
        if publish:
            clicked = await _click_first_match(
                page,
                [
                    'button:has-text("Publish")',
                    'button:has-text("Publish listing")',
                    '[data-clg-id*="publish" i]',
                    'button[type="submit"]:has-text("Publish")',
                ],
                label="publish",
            )
        else:
            clicked = await _click_first_match(
                page,
                [
                    'button:has-text("Save as draft")',
                    'button:has-text("Save draft")',
                    'button:has-text("Save for later")',
                    '[data-clg-id*="draft" i]',
                    'button:has-text("Save")',
                ],
                label="save draft",
            )

        await human_delay(2.0, 4.0)
        result = {
            "draft_id": draft["id"],
            "action": action,
            "title_filled": title_ok,
            "description_filled": desc_ok,
            "price_filled": price_ok,
            "tags_added": tags_added,
            "images_uploaded": images_uploaded,
            "submit_clicked": clicked,
            "final_url": page.url,
            "success": bool(title_ok and clicked),
        }

        if owns_page:
            await page.close()
        return result


async def run_browserclaw_upload(
    db: StoreDatabase,
    *,
    cdp_url: str | None = None,
    config_path: Path | None = None,
    draft_ids: list[int] | None = None,
    publish: bool = False,
    force_publish: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
    reuse_browser_tab: bool = True,
    extra_image_dirs: list[Path] | None = None,
    tracker: SwarmStateTracker | None = None,
) -> dict[str, Any]:
    """Upload one or more drafts via BrowserClaw with safety caps."""
    state = tracker or SwarmStateTracker()
    config = UploadConfig.load(config_path)
    endpoint = resolve_cdp_url(cdp_url)

    if publish and config.require_manual_upload and not force_publish:
        raise RuntimeError(
            "autopilot.yaml has require_manual_upload=true. "
            "Refusing --publish. Save as draft (default), set require_manual_upload=false, "
            "or pass --force-publish."
        )

    jobs = list_upload_jobs(db, draft_ids=draft_ids)
    if limit is not None:
        jobs = jobs[:limit]

    already = count_uploads_today(db)
    remaining = max(config.daily_upload_cap - already, 0)
    if remaining <= 0:
        return {
            "skipped": True,
            "reason": "daily_upload_cap",
            "daily_upload_cap": config.daily_upload_cap,
            "already_today": already,
            "jobs": [],
        }
    jobs = jobs[:remaining]

    if dry_run:
        return {
            "dry_run": True,
            "cdp_url": endpoint,
            "publish": publish,
            "daily_upload_cap": config.daily_upload_cap,
            "already_today": already,
            "queued": len(jobs),
            "jobs": [
                {
                    "id": job["id"],
                    "title": job["title"],
                    "price": job["price"],
                    "has_image": job["has_image"],
                    "image_path": job["image_path"],
                    "action": "publish" if publish else "save_draft",
                }
                for job in jobs
            ],
        }

    results: list[dict[str, Any]] = []
    with state.agent_activity("Uploader", "Uploading via BrowserClaw"):
        for index, job in enumerate(jobs, start=1):
            state.log(f"[{index}/{len(jobs)}] BrowserClaw upload draft #{job['id']}: {job['title'][:60]}")
            extras: list[Path] = []
            if extra_image_dirs:
                for directory in extra_image_dirs:
                    extras.extend(sorted(directory.glob("*.png")))
                    extras.extend(sorted(directory.glob("*.jpg")))
            try:
                outcome = await upload_listing_via_browserclaw(
                    job,
                    cdp_url=endpoint,
                    publish=publish,
                    reuse_browser_tab=reuse_browser_tab,
                    extra_images=extras[:4],
                )
                if outcome.get("success"):
                    mark_draft_uploaded(db, job["id"], published=publish, etsy_url=outcome.get("final_url"))
                    state.bump_metric("successful_uploads", 1)
                results.append(outcome)
            except Exception as exc:
                LOGGER.exception("BrowserClaw upload failed for draft %s", job["id"])
                state.log(f"Upload failed for draft #{job['id']}: {exc}", level="ERROR")
                results.append({"draft_id": job["id"], "success": False, "error": str(exc)})
            if index < len(jobs):
                await human_delay(4.0, 8.0)

    return {
        "cdp_url": endpoint,
        "publish": publish,
        "queued": len(jobs),
        "results": results,
        "successes": sum(1 for item in results if item.get("success")),
    }


def load_package_as_job(package_dir: Path) -> dict[str, Any]:
    """Load a listing package folder (listing.json + images/) as an upload job."""
    listing_path = package_dir / "listing.json"
    if not listing_path.exists():
        raise FileNotFoundError(f"No listing.json in {package_dir}")
    payload = json.loads(listing_path.read_text(encoding="utf-8"))
    images_dir = package_dir / "images"
    image_path = ""
    preferred = [
        images_dir / "01-hero-black-lifestyle.png",
        images_dir / "03-print-ready-graphic.png",
    ]
    for candidate in preferred:
        if candidate.exists():
            image_path = str(candidate)
            break
    if not image_path and images_dir.exists():
        pngs = sorted(images_dir.glob("*.png"))
        if pngs:
            image_path = str(pngs[0])
    return {
        "id": payload.get("listing_number") or 0,
        "title": payload["title"],
        "description": payload["description"],
        "tags": payload.get("tags") or [],
        "price": payload.get("price_usd") or payload.get("price") or 24.99,
        "image_path": image_path,
        "status": "package",
        "has_image": bool(image_path),
        "package_dir": str(package_dir),
    }


async def _cli(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    tracker = SwarmStateTracker()

    if args.list:
        jobs = list_upload_jobs(db, draft_ids=None)
        print(json.dumps(jobs, indent=2))
        return 0

    draft_ids = [int(value) for value in (args.draft_id or [])]
    extra_dirs = [Path(p) for p in (args.images_dir or [])]

    if args.package:
        package_job = load_package_as_job(Path(args.package))
        upload_cfg = UploadConfig.load(args.config)
        if args.publish and upload_cfg.require_manual_upload and not args.force_publish:
            raise RuntimeError(
                "autopilot.yaml has require_manual_upload=true. "
                "Refusing --publish. Save as draft (default), set require_manual_upload=false, "
                "or pass --force-publish."
            )
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "source": "package",
                        "job": package_job,
                        "action": "publish" if args.publish else "save_draft",
                    },
                    indent=2,
                )
            )
            return 0
        result = await upload_listing_via_browserclaw(
            package_job,
            cdp_url=resolve_cdp_url(args.cdp_url),
            publish=args.publish,
            reuse_browser_tab=args.reuse_tab,
            extra_images=list(Path(args.package).joinpath("images").glob("*.png"))[:5],
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("success") else 1

    result = await run_browserclaw_upload(
        db,
        cdp_url=args.cdp_url,
        config_path=args.config,
        draft_ids=draft_ids or None,
        publish=args.publish,
        force_publish=args.force_publish,
        dry_run=args.dry_run,
        limit=args.limit,
        reuse_browser_tab=args.reuse_tab,
        extra_image_dirs=extra_dirs or None,
        tracker=tracker,
    )
    print(json.dumps(result, indent=2))
    if result.get("skipped"):
        return 0
    if result.get("dry_run"):
        return 0
    return 0 if result.get("successes", 0) > 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload Etsy listing drafts via BrowserClaw (CDP) — draft by default",
    )
    parser.add_argument("--db", type=Path, default=None, help=f"SQLite path (default: {default_db_path()})")
    parser.add_argument("--config", type=Path, default=None, help="autopilot.yaml for upload caps")
    parser.add_argument("--cdp-url", default=None, help="BrowserClaw CDP URL (default env/9222)")
    parser.add_argument("--reuse-tab", action="store_true", help="Reuse active BrowserClaw tab")
    parser.add_argument("--list", action="store_true", help="List uploadable drafts and exit")
    parser.add_argument("--draft-id", action="append", help="Upload only this draft id (repeatable)")
    parser.add_argument("--package", type=Path, default=None, help="Upload from a listing package folder")
    parser.add_argument("--images-dir", action="append", help="Extra image directory to attach")
    parser.add_argument("--limit", type=int, default=None, help="Max listings to upload this run")
    parser.add_argument("--publish", action="store_true", help="Click Publish instead of Save as draft")
    parser.add_argument(
        "--force-publish",
        action="store_true",
        help="Allow --publish even when require_manual_upload=true",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show queue without driving the browser")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    raise SystemExit(asyncio.run(_cli(args)))


if __name__ == "__main__":
    main()
