"""Researcher agent — scrape trends and persist high performers."""

from __future__ import annotations

import logging
from typing import Protocol

from ...db import StoreDatabase
from ...models import ScrapedListing
from ...scraper.demo import DemoScraperBackend
from ...scraper.playwright import PlaywrightScraperBackend

LOGGER = logging.getLogger(__name__)


class ScraperBackend(Protocol):
    source: str

    async def scrape_search(self, query: str, *, max_results: int = 48) -> list[ScrapedListing]:
        ...


async def run_researcher(
    query: str,
    db: StoreDatabase,
    *,
    backend: ScraperBackend | None = None,
    max_results: int = 48,
    min_score: float = 35.0,
) -> dict[str, object]:
    """Scrape Etsy search results and store listings above the score threshold."""
    scraper = backend or DemoScraperBackend()
    run = db.start_scrape_run(query=query, source=scraper.source)
    assert run.id is not None

    try:
        listings = await scraper.scrape_search(query, max_results=max_results)
        kept = [item for item in listings if (item.performance_score or 0.0) >= min_score]
        inserted = db.insert_listings(run.id, kept)
        db.finish_scrape_run(run.id, listing_count=inserted, status="completed")
        LOGGER.info(
            "Researcher stored %d/%d listings for %r (source=%s)",
            inserted,
            len(listings),
            query,
            scraper.source,
        )
        return {
            "run_id": run.id,
            "query": query,
            "source": scraper.source,
            "scraped": len(listings),
            "stored": inserted,
            "top": [item.to_row() for item in kept[:5]],
        }
    except Exception as exc:
        LOGGER.exception("Researcher scrape failed for %r", query)
        db.finish_scrape_run(run.id, listing_count=0, status=f"failed: {exc}")
        raise


def build_scraper(*, demo: bool, headless: bool = True) -> ScraperBackend:
    if demo:
        return DemoScraperBackend()
    return PlaywrightScraperBackend(headless=headless)
