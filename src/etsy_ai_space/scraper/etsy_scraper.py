"""Playwright Etsy scraper — search a niche, scroll results, save to SQLite."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from ..db import StoreDatabase, default_db_path
from ..scoring import score_listing
from ..scraper.demo import DemoScraperBackend
from ..scraper.playwright import PlaywrightScraperBackend
from ..tools.delays import human_delay

LOGGER = logging.getLogger(__name__)


async def scrape_niche_to_db(
    query: str,
    db: StoreDatabase,
    *,
    demo: bool = False,
    max_results: int = 48,
    min_score: float = 35.0,
    headless: bool = True,
) -> dict[str, object]:
    """Search Etsy for a niche, extract listing metadata, persist high performers."""
    scraper = DemoScraperBackend() if demo else PlaywrightScraperBackend(headless=headless)
    run = db.start_scrape_run(query=query, source=scraper.source)
    assert run.id is not None

    try:
        LOGGER.info("Scraping niche %r via %s", query, scraper.source)
        listings = await scraper.scrape_search(query, max_results=max_results)
        for item in listings:
            score_listing(item)

        kept = [item for item in listings if (item.performance_score or 0.0) >= min_score]
        stored = db.insert_listings(run.id, kept)
        db.finish_scrape_run(run.id, listing_count=stored, status="completed")

        return {
            "run_id": run.id,
            "query": query,
            "source": scraper.source,
            "scraped": len(listings),
            "stored": stored,
            "top": [item.to_row() for item in kept[:5]],
        }
    except Exception as exc:
        LOGGER.exception("Scrape failed for %r", query)
        db.finish_scrape_run(run.id, listing_count=0, status=f"failed: {exc}")
        raise


async def _cli(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    result = await scrape_niche_to_db(
        args.query,
        db,
        demo=args.demo,
        max_results=args.max_results,
        min_score=args.min_score,
        headless=args.headless,
    )
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape Etsy search results into SQLite")
    parser.add_argument("query", help="Niche search query, e.g. 'retro cat shirt'")
    parser.add_argument("--db", type=Path, default=None, help=f"SQLite path (default: {default_db_path()})")
    parser.add_argument("--demo", action="store_true", help="Use offline demo listings")
    parser.add_argument("--max-results", type=int, default=48)
    parser.add_argument("--min-score", type=float, default=35.0)
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    raise SystemExit(asyncio.run(_cli(args)))


if __name__ == "__main__":
    main()
