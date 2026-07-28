"""Etsy trend scraper backends."""

from __future__ import annotations

from typing import Protocol

from ..models import ScrapedListing


class ScraperBackend(Protocol):
    async def scrape_search(self, query: str, *, max_results: int = 48) -> list[ScrapedListing]:
        """Return listing observations for a search query."""
