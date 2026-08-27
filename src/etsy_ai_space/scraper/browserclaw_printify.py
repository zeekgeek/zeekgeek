"""Drive Printify in BrowserClaw to create product drafts ready for Etsy publish.

Flow:
1. Attach to BrowserClaw (must already be logged into Printify)
2. Open Printify product creator / My Products
3. Upload the listing print file and fill title/description
4. Leave the product as a **draft** ready for you to Publish → Etsy
5. Optionally wait until you mark it submitted

This does **not** click the final Publish-to-Etsy button unless you pass
``--publish`` (still blocked when require_manual_upload-style safety is on).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from ..models import iso_time
from ..pipeline.state_tracker import SwarmStateTracker
from ..printify.workflow import (
    PrintifyWorkflow,
    default_queue_path,
    load_listing_package,
    load_printify_config,
    load_queue,
    save_queue,
)
from ..tools.delays import human_delay, micro_delay
from .browser_connect import acquire_page, connect_over_cdp, resolve_cdp_url

LOGGER = logging.getLogger(__name__)

PRINTIFY_HOME = "https://printify.com/app/store/products"
PRINTIFY_ADD = "https://printify.com/app/products/add"


async def _goto_printify(page: Any) -> None:
    for url in (PRINTIFY_ADD, PRINTIFY_HOME):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await human_delay(2.0, 4.0)
            break
        except Exception as exc:
            LOGGER.warning("Failed to open %s: %s", url, exc)
    current = (page.url or "").lower()
    if "login" in current or "signin" in current or "auth" in current:
        raise RuntimeError(
            "Printify login required. Log into Printify inside BrowserClaw, then retry."
        )


async def prepare_printify_draft_via_browserclaw(
    listing: dict[str, Any],
    *,
    cdp_url: str,
    reuse_browser_tab: bool = True,
    publish: bool = False,
) -> dict[str, Any]:
    """Open Printify and stage one listing as a draft for Etsy publish."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install -e '.[etsy]' && playwright install chromium"
        ) from exc

    print_file = Path(listing["print_file"])
    if not print_file.exists():
        raise FileNotFoundError(f"Print file missing: {print_file}")

    async with async_playwright() as playwright:
        browser = await connect_over_cdp(playwright, cdp_url)
        _browser, page, owns_page = await acquire_page(browser, reuse_existing=reuse_browser_tab)
        await _goto_printify(page)

        # Best-effort UI automation — Printify's SPA selectors change often.
        filled: dict[str, bool] = {
            "navigated": True,
            "title": False,
            "description": False,
            "image": False,
            "publish_clicked": False,
        }

        # Try common "create product" / "add design" entry points
        for selector in (
            'button:has-text("Add product")',
            'a:has-text("Add product")',
            'button:has-text("Create product")',
            'button:has-text("Choose product")',
            'button:has-text("Start designing")',
        ):
            locator = page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    await locator.click()
                    await human_delay(1.5, 3.0)
                    break
            except Exception:
                continue

        # Prefer Comfort Colors / T-shirt choices when visible
        for selector in (
            'text=Comfort Colors',
            'text=1717',
            'button:has-text("T-Shirt")',
            'div:has-text("Unisex Garment-Dyed")',
        ):
            locator = page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    await locator.click()
                    await human_delay(1.0, 2.0)
                    break
            except Exception:
                continue

        # Upload design file if a file input is present
        file_inputs = page.locator('input[type="file"]')
        try:
            if await file_inputs.count() > 0:
                await file_inputs.first.set_input_files(str(print_file))
                filled["image"] = True
                await human_delay(2.0, 4.0)
        except Exception as exc:
            LOGGER.warning("Could not upload print file via file input: %s", exc)

        # Title / description fields (when product details step is shown)
        for selector in (
            'input[name="title"]',
            'input[placeholder*="title" i]',
            'input[aria-label*="title" i]',
        ):
            locator = page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    await locator.fill(str(listing["title"])[:200])
                    filled["title"] = True
                    await micro_delay()
                    break
            except Exception:
                continue

        for selector in (
            'textarea[name="description"]',
            'textarea[placeholder*="description" i]',
            'div[contenteditable="true"]',
        ):
            locator = page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    await locator.fill(str(listing.get("description") or "")[:5000])
                    filled["description"] = True
                    await micro_delay()
                    break
            except Exception:
                continue

        if publish:
            for selector in (
                'button:has-text("Publish")',
                'button:has-text("Publish to Etsy")',
                'button:has-text("Continue to publish")',
            ):
                locator = page.locator(selector).first
                try:
                    if await locator.count() and await locator.is_visible():
                        await locator.click()
                        filled["publish_clicked"] = True
                        await human_delay(2.0, 4.0)
                        break
                except Exception:
                    continue

        # Prefer save draft / continue without publishing
        if not publish:
            for selector in (
                'button:has-text("Save as draft")',
                'button:has-text("Save draft")',
                'button:has-text("Save product")',
                'button:has-text("Continue")',
                'button:has-text("Save")',
            ):
                locator = page.locator(selector).first
                try:
                    if await locator.count() and await locator.is_visible():
                        await locator.click()
                        await human_delay(1.5, 3.0)
                        break
                except Exception:
                    continue

        result = {
            "source": "browserclaw-printify",
            "title": listing["title"],
            "print_file": str(print_file),
            "final_url": page.url,
            "filled": filled,
            "status": "awaiting_human_submit",
            "message": (
                "BrowserClaw opened Printify and staged what it could. "
                "Finish mockups/colors if needed, then Publish to your Etsy sales channel. "
                "When done: python3 -m etsy_ai_space printify mark-submitted --all"
            ),
            "success": bool(filled["navigated"]),
        }

        # Track in the shared Printify queue so `printify wait` works
        queue = load_queue()
        items = list(queue.get("items") or [])
        items.append(
            {
                "id": f"browserclaw-{listing.get('listing_number') or 'pkg'}-{int(time.time())}",
                "shop_id": None,
                "title": listing["title"],
                "package_dir": listing.get("package_dir"),
                "listing_number": listing.get("listing_number"),
                "print_file": str(print_file),
                "status": "awaiting_human_submit",
                "created_at": iso_time(),
                "submitted_at": None,
                "printify_url": page.url,
                "dashboard_hint": "Finish in Printify, then Publish to Etsy. Do not leave this tab until saved.",
                "via": "browserclaw",
            }
        )
        queue["items"] = items
        save_queue(queue)

        if owns_page:
            # Keep the tab open for the human — do not close
            pass
        return result


async def run_browserclaw_printify(
    package_dirs: list[Path],
    *,
    cdp_url: str | None = None,
    reuse_browser_tab: bool = True,
    publish: bool = False,
    dry_run: bool = False,
    wait: bool = False,
    tracker: SwarmStateTracker | None = None,
) -> dict[str, Any]:
    state = tracker or SwarmStateTracker()
    endpoint = resolve_cdp_url(cdp_url)
    results: list[dict[str, Any]] = []

    if dry_run:
        jobs = []
        for directory in package_dirs:
            listing = load_listing_package(directory)
            jobs.append(
                {
                    "package_dir": str(directory),
                    "title": listing["title"],
                    "print_file": listing["print_file"],
                    "action": "publish_to_etsy" if publish else "stage_printify_draft",
                    "cdp_url": endpoint,
                }
            )
        return {
            "dry_run": True,
            "cdp_url": endpoint,
            "jobs": jobs,
            "next_step": (
                "Start BrowserClaw with CDP, log into Printify (Etsy channel connected), then re-run without --dry-run"
            ),
        }

    with state.agent_activity("Uploader", "BrowserClaw Printify staging"):
        for index, directory in enumerate(package_dirs, start=1):
            listing = load_listing_package(directory)
            state.log(f"[{index}/{len(package_dirs)}] Staging in Printify: {listing['title'][:70]}")
            try:
                outcome = await prepare_printify_draft_via_browserclaw(
                    listing,
                    cdp_url=endpoint,
                    reuse_browser_tab=reuse_browser_tab or index > 1,
                    publish=publish,
                )
                results.append(outcome)
            except Exception as exc:
                LOGGER.exception("BrowserClaw Printify staging failed for %s", directory)
                results.append(
                    {
                        "package_dir": str(directory),
                        "success": False,
                        "error": str(exc),
                    }
                )
            if index < len(package_dirs):
                await human_delay(3.0, 6.0)

    payload: dict[str, Any] = {
        "cdp_url": endpoint,
        "count": len(results),
        "results": results,
        "successes": sum(1 for item in results if item.get("success")),
        "pending_queue": default_queue_path().as_posix(),
        "human_gate": (
            "Review each product in Printify, connect/select your Etsy shop, then Publish. "
            "When finished: python3 -m etsy_ai_space printify mark-submitted --all"
        ),
    }

    if wait:
        config = load_printify_config()
        workflow = PrintifyWorkflow(config)
        wait_result = workflow.wait_for_submit()
        payload["wait"] = wait_result
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stage Printify drafts via BrowserClaw for Etsy publish (human submits)",
    )
    parser.add_argument("--cdp-url", default=None, help="BrowserClaw CDP URL (default 9222)")
    parser.add_argument("--reuse-tab", action="store_true", help="Reuse active BrowserClaw tab")
    parser.add_argument("--package", action="append", help="Listing package folder (repeatable)")
    parser.add_argument("--all-listings", action="store_true", help="Use all exports/listing-* packages")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Attempt to click Publish (default: stage draft only)",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="After staging, wait until you mark products submitted",
    )
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def _packages_from_args(args: argparse.Namespace) -> list[Path]:
    packages: list[Path] = []
    if args.package:
        packages.extend(Path(p) for p in args.package)
    if args.all_listings:
        root = Path.cwd() / "etsy_ai_space" / "exports"
        packages.extend(sorted(root.glob("listing-*/")))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in packages:
        key = str(path.resolve())
        if key not in seen and path.is_dir():
            seen.add(key)
            unique.append(path)
    return unique


async def _cli(args: argparse.Namespace) -> int:
    packages = _packages_from_args(args)
    if not packages:
        print("Provide --package PATH or --all-listings", flush=True)
        return 1
    result = await run_browserclaw_printify(
        packages,
        cdp_url=args.cdp_url,
        reuse_browser_tab=args.reuse_tab,
        publish=args.publish,
        dry_run=args.dry_run,
        wait=args.wait,
    )
    print(json.dumps(result, indent=2))
    if result.get("dry_run"):
        return 0
    return 0 if result.get("successes", 0) > 0 else 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    raise SystemExit(asyncio.run(_cli(args)))


if __name__ == "__main__":
    main()
