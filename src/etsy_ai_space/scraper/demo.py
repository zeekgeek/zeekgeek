"""Demo scraper — safe offline trend data for development and CI."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from ..models import ScrapedListing
from ..scoring import score_listing
from ..tools.delays import human_delay


DEMO_TEMPLATES: dict[str, list[dict[str, object]]] = {
    "retro cat": [
        {
            "title": "Retro Sunset Cat Lover Tee | Vintage 70s Graphic Shirt",
            "shop_name": "InkAndWhiskerCo",
            "price": 24.99,
            "reviews": 842,
            "rating": 4.9,
            "favorites": 3200,
            "tags": ["retro cat shirt", "vintage tee", "sunset graphic", "cat mom gift"],
        },
        {
            "title": "Funny Cat Coffee Shirt | Sarcastic Morning Person Tee",
            "shop_name": "PurrPrintStudio",
            "price": 22.50,
            "reviews": 1204,
            "rating": 4.8,
            "favorites": 5100,
            "tags": ["cat coffee shirt", "funny cat tee", "sarcastic shirt"],
        },
        {
            "title": "Minimal Line Art Cat Shirt | Neutral Aesthetic Tee",
            "shop_name": "QuietLineGoods",
            "price": 26.00,
            "reviews": 311,
            "rating": 4.7,
            "favorites": 980,
            "tags": ["line art cat", "minimalist tee", "neutral aesthetic"],
        },
    ],
    "default": [
        {
            "title": "Funny Pickle Lover Shirt | Dill Pickle Humor Tee",
            "shop_name": "BrineAndDesign",
            "price": 23.99,
            "reviews": 650,
            "rating": 4.8,
            "favorites": 2100,
            "tags": ["pickle shirt", "funny food tee", "dill pickle lover"],
        },
        {
            "title": "Cottagecore Mushroom Shirt | Forest Foraging Graphic Tee",
            "shop_name": "MossyThread",
            "price": 25.50,
            "reviews": 980,
            "rating": 4.9,
            "favorites": 4300,
            "tags": ["cottagecore shirt", "mushroom tee", "forest aesthetic"],
        },
        {
            "title": "Retro Bowling Shirt | Vintage Strike Graphic Tee",
            "shop_name": "LaneLegends",
            "price": 21.99,
            "reviews": 402,
            "rating": 4.6,
            "favorites": 760,
            "tags": ["bowling shirt", "retro sports tee", "strike graphic"],
        },
        {
            "title": "Book Lover Stack Shirt | Reading Nook Graphic Tee",
            "shop_name": "ShelfLifeTees",
            "price": 24.00,
            "reviews": 1550,
            "rating": 4.9,
            "favorites": 6200,
            "tags": ["book lover shirt", "reading tee", "librarian gift"],
        },
    ],
}


class DemoScraperBackend:
    """Simulates a successful Etsy search scrape without network access."""

    source = "demo"

    async def scrape_search(self, query: str, *, max_results: int = 48) -> list[ScrapedListing]:
        await human_delay(0.5, 1.5)
        key = "default"
        lowered = query.lower()
        for template_key in DEMO_TEMPLATES:
            if template_key in lowered:
                key = template_key
                break
        templates = DEMO_TEMPLATES[key]
        now = datetime.now(UTC)
        listings: list[ScrapedListing] = []
        for index, template in enumerate(templates[:max_results]):
            listing_id = f"demo-{abs(hash(query)) % 100000}-{index}"
            listing = ScrapedListing(
                etsy_listing_id=listing_id,
                title=str(template["title"]),
                url=f"https://www.etsy.com/listing/{listing_id}",
                price_amount=float(template["price"]),
                shop_name=str(template["shop_name"]),
                review_count=int(template["reviews"]),
                rating=float(template["rating"]),
                favorites=int(template["favorites"]),
                tags=list(template["tags"]),  # type: ignore[arg-type]
                scraped_at=now,
            )
            # Slight jitter so repeated demo runs still sort interestingly.
            listing.review_count = (listing.review_count or 0) + random.randint(-20, 40)
            score_listing(listing)
            listings.append(listing)
        listings.sort(key=lambda item: item.performance_score or 0.0, reverse=True)
        return listings
