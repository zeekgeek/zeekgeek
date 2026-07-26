"""Headless Playwright scraper with humanized pacing and polite rate limits."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from ..models import ScrapedListing, utc_now
from ..scoring import score_listing
from ..tools.delays import micro_delay
from .rate_limit import (
    MAX_DELAY_SECONDS,
    MIN_DELAY_SECONDS,
    EtsyRateLimiter,
    polite_goto,
)

LOGGER = logging.getLogger(__name__)

LISTING_ID_RE = re.compile(r"/listing/(\d+)")


class PlaywrightScraperBackend:
    """Scrape Etsy search results via a real browser session."""

    source = "playwright"

    def __init__(
        self,
        *,
        headless: bool = True,
        min_delay: float = MIN_DELAY_SECONDS,
        max_delay: float = MAX_DELAY_SECONDS,
        user_agent: str | None = None,
        rate_limiter: EtsyRateLimiter | None = None,
    ) -> None:
        self.headless = headless
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        self.rate_limiter = rate_limiter or EtsyRateLimiter(
            min_delay=min_delay,
            max_delay=max_delay,
        )

    async def scrape_search(self, query: str, *, max_results: int = 48) -> list[ScrapedListing]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            ) from exc

        url = f"https://www.etsy.com/search?q={quote_plus(query)}&explicit=1"
        listings: list[ScrapedListing] = []
        now = utc_now()

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent=self.user_agent,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
            )
            page = await context.new_page()

            def _on_response(response: Any) -> None:
                try:
                    if "etsy.com" not in response.url:
                        return
                    status = response.status
                    if status >= 400:
                        LOGGER.info(
                            "rate-limit: observed response url=%s status=%d",
                            response.url[:120],
                            status,
                        )
                except Exception:
                    pass

            page.on("response", _on_response)

            try:
                await polite_goto(
                    page,
                    url,
                    self.rate_limiter,
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                await self._gentle_scroll(page)
                cards = page.locator("[data-listing-id], a.listing-link")
                count = await cards.count()
                LOGGER.info("Playwright found %d candidate cards for %r", count, query)
                seen: set[str] = set()
                for index in range(min(count, max_results * 2)):
                    card = cards.nth(index)
                    parsed = await self._parse_card(card, now)
                    if parsed is None:
                        continue
                    key = parsed.etsy_listing_id or parsed.url
                    if key in seen:
                        continue
                    seen.add(key)
                    score_listing(parsed)
                    listings.append(parsed)
                    if len(listings) >= max_results:
                        break
                    await micro_delay()
            finally:
                await context.close()
                await browser.close()

        stats = self.rate_limiter.stats
        LOGGER.info(
            "rate-limit: session complete requests=%d rate_limit_events=%d total_sleep=%.1fs",
            stats.requests,
            stats.rate_limit_events,
            stats.total_sleep_seconds,
        )
        listings.sort(key=lambda item: item.performance_score or 0.0, reverse=True)
        return listings

    async def _gentle_scroll(self, page: Any) -> None:
        for _ in range(3):
            await page.mouse.wheel(0, 900)
            await micro_delay(0.4, 1.0)

    async def _parse_card(self, card: Any, scraped_at: Any) -> ScrapedListing | None:
        listing_id = await card.get_attribute("data-listing-id")
        href = await card.get_attribute("href")
        if not listing_id and href:
            match = LISTING_ID_RE.search(href)
            listing_id = match.group(1) if match else None

        title = await self._first_text(
            card,
            [
                "h3",
                "[data-listing-card-title]",
                ".v2-listing-card__title",
            ],
        )
        if not title:
            title = (await card.inner_text()).strip().split("\n", 1)[0].strip()
        if not title:
            return None

        price_text = await self._first_text(card, ["span.currency-value", ".currency-value", "[data-price]"])
        price_amount = self._parse_price(price_text)
        shop_name = await self._first_text(card, [".shop-name", "[data-shop-name]"])

        url = href or ""
        if url.startswith("/"):
            url = f"https://www.etsy.com{url}"
        if not url and listing_id:
            url = f"https://www.etsy.com/listing/{listing_id}"

        return ScrapedListing(
            etsy_listing_id=listing_id,
            title=title[:240],
            url=url,
            price_amount=price_amount,
            shop_name=shop_name,
            scraped_at=scraped_at,
        )

    @staticmethod
    async def _first_text(root: Any, selectors: list[str]) -> str | None:
        for selector in selectors:
            locator = root.locator(selector).first
            if await locator.count() == 0:
                continue
            text = (await locator.inner_text()).strip()
            if text:
                return text
        return None

    @staticmethod
    def _parse_price(raw: str | None) -> float | None:
        if not raw:
            return None
        cleaned = re.sub(r"[^\d.]", "", raw.replace(",", ""))
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
