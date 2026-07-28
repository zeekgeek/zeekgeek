"""Scrape Etsy niches via an active BrowserClaw Chromium instance (CDP attach)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import yaml

from ..db import StoreDatabase, default_db_path
from ..pipeline.state_tracker import SwarmStateTracker
from ..scoring import score_listing
from ..tools.delays import human_delay
from .browser_connect import resolve_cdp_url
from .etsy_scraper import scrape_niche_to_db
from .playwright import PlaywrightScraperBackend

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG = Path.cwd() / "etsy_ai_space" / "autopilot.yaml"


def load_niches(config_path: Path | None = None) -> list[str]:
    """Load target niches from autopilot.yaml."""
    path = config_path or DEFAULT_CONFIG
    if not path.exists():
        raise FileNotFoundError(f"Autopilot config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    niches = data.get("niches") or []
    if not isinstance(niches, list) or not niches:
        raise ValueError(f"No niches configured in {path}")
    return [str(item).strip() for item in niches if str(item).strip()]


async def scrape_niches_via_browserclaw(
    cdp_url: str,
    db: StoreDatabase,
    niches: list[str],
    *,
    max_results: int = 24,
    min_score: float = 35.0,
    reuse_browser_tab: bool = False,
    tracker: SwarmStateTracker | None = None,
) -> dict[str, Any]:
    """Connect to BrowserClaw once and scrape each niche into SQLite."""
    state = tracker or SwarmStateTracker()
    scraper = PlaywrightScraperBackend(
        cdp_url=cdp_url,
        reuse_browser_tab=reuse_browser_tab,
    )
    results: list[dict[str, object]] = []
    total_stored = 0

    state.log(f"BrowserClaw scraper attached via {cdp_url}")
    for index, niche in enumerate(niches, start=1):
        run = db.start_scrape_run(query=niche, source=scraper.source)
        assert run.id is not None
        state.log(f"[{index}/{len(niches)}] Scraping niche: {niche}")
        try:
            listings = await scraper.scrape_search(niche, max_results=max_results)
            for item in listings:
                score_listing(item)
            kept = [item for item in listings if (item.performance_score or 0.0) >= min_score]
            stored = db.insert_listings(run.id, kept)
            db.finish_scrape_run(run.id, listing_count=stored, status="completed")
            total_stored += stored
            payload = {
                "run_id": run.id,
                "query": niche,
                "source": scraper.source,
                "scraped": len(listings),
                "stored": stored,
                "top": [item.to_row() for item in kept[:3]],
            }
            results.append(payload)
            state.log(f"Stored {stored}/{len(listings)} listings for {niche!r}")
        except Exception as exc:
            LOGGER.exception("BrowserClaw scrape failed for %r", niche)
            db.finish_scrape_run(run.id, listing_count=0, status=f"failed: {exc}")
            state.log(f"Scrape failed for {niche!r}: {exc}", level="ERROR")
            results.append({"query": niche, "error": str(exc), "stored": 0})

        if index < len(niches):
            await human_delay(4.0, 9.0)

    return {
        "cdp_url": cdp_url,
        "niches": niches,
        "runs": results,
        "total_stored": total_stored,
    }


async def _cli(args: argparse.Namespace) -> int:
    cdp_url = resolve_cdp_url(args.cdp_url)
    db = StoreDatabase(args.db)
    tracker = SwarmStateTracker()

    if args.query:
        niches = [args.query]
    else:
        niches = load_niches(args.config)

    with tracker.agent_activity("Scraper", "BrowserClaw CDP scrape"):
        if args.query and not args.all_niches:
            result = await scrape_niche_to_db(
                args.query,
                db,
                demo=False,
                max_results=args.max_results,
                min_score=args.min_score,
                headless=False,
                tracker=tracker,
                cdp_url=cdp_url,
                reuse_browser_tab=args.reuse_tab,
            )
        else:
            result = await scrape_niches_via_browserclaw(
                cdp_url,
                db,
                niches,
                max_results=args.max_results,
                min_score=args.min_score,
                reuse_browser_tab=args.reuse_tab,
                tracker=tracker,
            )

    tracker.bump_metric("scrape_runs", len(niches))
    tracker.set_agent("Scraper", "Idle")
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Attach Playwright to a running BrowserClaw instance via CDP, "
            "search Etsy niches, and save listing metadata to SQLite."
        ),
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Optional single niche query (default: all niches from autopilot.yaml)",
    )
    parser.add_argument(
        "--cdp-url",
        default=None,
        help=(
            "BrowserClaw CDP endpoint (http://127.0.0.1:9222 or ws://…/devtools/browser/…). "
            "Defaults to BROWSERCLAW_CDP_URL env var, then http://127.0.0.1:9222."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="autopilot.yaml path for niche list",
    )
    parser.add_argument(
        "--all-niches",
        action="store_true",
        help="Scrape every niche in autopilot.yaml even when query is provided",
    )
    parser.add_argument("--db", type=Path, default=None, help=f"SQLite path (default: {default_db_path()})")
    parser.add_argument("--max-results", type=int, default=24)
    parser.add_argument("--min-score", type=float, default=35.0)
    parser.add_argument(
        "--reuse-tab",
        action="store_true",
        help="Reuse the active BrowserClaw tab instead of opening a new one per niche",
    )
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    raise SystemExit(asyncio.run(_cli(args)))


if __name__ == "__main__":
    main()
