"""Headless Playwright scraper with humanized pacing and polite rate limits."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from ..models import ScrapedListing, utc_now
from ..scoring import score_listing
from ..tools.delays import human_delay, micro_delay
from ..tools.scroll import natural_scroll
from .browser_connect import acquire_page, connect_over_cdp
from .rate_limit import (
    MAX_DELAY_SECONDS,
    MIN_DELAY_SECONDS,
    EtsyRateLimiter,
    polite_goto,
)

LOGGER = logging.getLogger(__name__)

LISTING_ID_RE = re.compile(r"/listing/(\d+)")
REVIEW_COUNT_RE = re.compile(r"(\d[\d,]*)\s*reviews?", re.IGNORECASE)
FAVORITES_RE = re.compile(r"(\d[\d,]*)\s*favorites?", re.IGNORECASE)
RATING_OUT_OF_RE = re.compile(r"(\d(?:\.\d)?)\s*out of\s*5", re.IGNORECASE)
RATING_PAREN_RE = re.compile(r"(\d\.\d)\s*\(\s*(\d[\d,]*)(?:\s*reviews?)?\s*\)", re.IGNORECASE)
BESTSELLER_RE = re.compile(r"bestseller|popular now|etsy'?s pick", re.IGNORECASE)


class PlaywrightScraperBackend:
    """Scrape Etsy search results via Playwright (launch or CDP attach)."""

    source = "playwright"

    def __init__(
        self,
        *,
        headless: bool = True,
        min_delay: float = MIN_DELAY_SECONDS,
        max_delay: float = MAX_DELAY_SECONDS,
        user_agent: str | None = None,
        rate_limiter: EtsyRateLimiter | None = None,
        cdp_url: str | None = None,
        reuse_browser_tab: bool = False,
    ) -> None:
        self.headless = headless
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.cdp_url = cdp_url
        self.reuse_browser_tab = reuse_browser_tab
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        self.rate_limiter = rate_limiter or EtsyRateLimiter(
            min_delay=min_delay,
            max_delay=max_delay,
        )
        if cdp_url:
            self.source = "browserclaw"

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
        attached = self.cdp_url is not None

        async with async_playwright() as playwright:
            browser: Any
            owns_browser = False
            if attached:
                LOGGER.info("Connecting to BrowserClaw/CDP at %s", self.cdp_url)
                browser = await connect_over_cdp(playwright, self.cdp_url or "")
            else:
                browser = await playwright.chromium.launch(headless=self.headless)
                owns_browser = True

            context = None
            page: Any
            owns_page = False
            try:
                if attached:
                    browser, page, owns_page = await acquire_page(
                        browser,
                        reuse_existing=self.reuse_browser_tab,
                    )
                else:
                    context = await browser.new_context(
                        user_agent=self.user_agent,
                        viewport={"width": 1366, "height": 900},
                        locale="en-US",
                    )
                    page = await context.new_page()
                    owns_page = True

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

                await polite_goto(
                    page,
                    url,
                    self.rate_limiter,
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                await human_delay(self.min_delay, self.max_delay)
                await natural_scroll(page)
                await human_delay(0.8, 2.0)

                cards = page.locator(
                    "[data-listing-id], a.listing-link, div[data-listing-card-v2], li.wt-list-unstyled"
                )
                count = await cards.count()
                LOGGER.info("Playwright found %d candidate cards for %r", count, query)
                seen: set[str] = set()
                for index in range(min(count, max_results * 3)):
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
                if owns_page and not self.reuse_browser_tab:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if context is not None:
                    await context.close()
                if owns_browser:
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
                ".wt-text-caption",
            ],
        )
        card_text = ""
        try:
            card_text = (await card.inner_text()).strip()
        except Exception:
            pass
        if not title and card_text:
            title = card_text.split("\n", 1)[0].strip()
        if not title:
            return None

        price_text = await self._first_text(
            card,
            ["span.currency-value", ".currency-value", "[data-price]", ".lc-price"],
        )
        price_amount = self._parse_price(price_text) or self._parse_price(card_text)
        shop_name = await self._first_text(
            card,
            [".shop-name", "[data-shop-name]", ".v2-listing-card__shop"],
        )

        review_count, rating, favorites = self._parse_signals(card_text)
        if review_count is None or rating is None:
            aria = await card.get_attribute("aria-label") or ""
            extra_review, extra_rating, extra_fav = self._parse_signals(aria)
            review_count = review_count if review_count is not None else extra_review
            rating = rating if rating is not None else extra_rating
            favorites = favorites if favorites is not None else extra_fav

        if favorites is None and BESTSELLER_RE.search(card_text):
            favorites = 500

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
            review_count=review_count,
            rating=rating,
            favorites=favorites,
            scraped_at=scraped_at,
        )

    @staticmethod
    def _parse_signals(text: str) -> tuple[int | None, float | None, int | None]:
        review_count: int | None = None
        rating: float | None = None
        favorites: int | None = None

        rating_paren = RATING_PAREN_RE.search(text)
        if rating_paren:
            rating = float(rating_paren.group(1))
            review_count = PlaywrightScraperBackend._parse_int(rating_paren.group(2))

        review_match = REVIEW_COUNT_RE.search(text)
        if review_match:
            review_count = PlaywrightScraperBackend._parse_int(review_match.group(1))

        rating_match = RATING_OUT_OF_RE.search(text)
        if rating_match:
            rating = float(rating_match.group(1))

        fav_match = FAVORITES_RE.search(text)
        if fav_match:
            favorites = PlaywrightScraperBackend._parse_int(fav_match.group(1))

        return review_count, rating, favorites

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
    def _parse_int(raw: str | None) -> int | None:
        if not raw:
            return None
        cleaned = re.sub(r"[^\d]", "", raw)
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except ValueError:
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
