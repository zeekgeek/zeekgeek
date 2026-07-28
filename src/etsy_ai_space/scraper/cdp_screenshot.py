"""Open a URL in an attached Chrome/BrowserClaw session and save a screenshot."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .browser_connect import (
    cdp_setup_hint,
    discover_cdp_url,
    probe_cdp_url,
    resolve_cdp_url,
)


async def capture_screenshot(url: str, cdp_url: str, output: Path) -> Path:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
            await page.screenshot(path=str(output), full_page=False)
        finally:
            await page.close()
    return output.resolve()


def cmd_check(cdp_url: str | None) -> int:
    explicit = resolve_cdp_url(cdp_url) if cdp_url else None
    if explicit:
        info = probe_cdp_url(explicit)
        if info:
            print(f"CDP OK: {explicit}")
            print(f"Browser: {info.get('Browser', 'unknown')}")
            return 0
        print(f"CDP not reachable at {explicit}")
        print(cdp_setup_hint())
        return 1

    found = discover_cdp_url()
    if found:
        info = probe_cdp_url(found) or {}
        print(f"CDP OK: {found}")
        print(f"Browser: {info.get('Browser', 'unknown')}")
        return 0

    print(cdp_setup_hint())
    return 1


async def cmd_capture(url: str, cdp_url: str | None, output: Path) -> int:
    chosen = resolve_cdp_url(cdp_url) if cdp_url else discover_cdp_url()
    if not chosen or not probe_cdp_url(chosen):
        print(cdp_setup_hint(), file=sys.stderr)
        return 1

    path = await capture_screenshot(url, chosen, output)
    print(f"Saved screenshot: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CDP screenshot helper for BrowserClaw / Chrome")
    parser.add_argument("--check", action="store_true", help="Only verify CDP is reachable")
    parser.add_argument("--url", default="https://www.etsy.com/search?q=recovery+definition+shirt")
    parser.add_argument("--cdp-url", default=None, help="CDP endpoint (default: scan 9222-9229)")
    parser.add_argument("--output", type=Path, default=Path("etsy_recovery_definition.png"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.check:
        raise SystemExit(cmd_check(args.cdp_url))
    raise SystemExit(asyncio.run(cmd_capture(args.url, args.cdp_url, args.output)))


if __name__ == "__main__":
    main()
