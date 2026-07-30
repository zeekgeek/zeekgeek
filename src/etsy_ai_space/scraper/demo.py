"""Demo scraper — safe offline trend data for development and CI."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from ..models import ScrapedListing
from ..scoring import score_listing
from ..tools.delays import human_delay


DEMO_TEMPLATES: dict[str, list[dict[str, object]]] = {
    "sober": [
        {
            "title": "Namastay Sober Shirt | Funny Sobriety Yoga Recovery Gift Tee",
            "shop_name": "MindfulRecoveryTees",
            "price": 24.99,
            "reviews": 3600,
            "rating": 5.0,
            "favorites": 8200,
            "tags": ["namastay sober", "sobriety shirt", "yoga recovery", "funny sober gift"],
        },
        {
            "title": "Custom Soberversary Comfort Colors Tee | Est Date Recovery Milestone",
            "shop_name": "MilestoneThreadCo",
            "price": 29.75,
            "reviews": 352,
            "rating": 4.9,
            "favorites": 3400,
            "tags": ["soberversary gift", "comfort colors", "custom date shirt", "sobriety milestone"],
        },
        {
            "title": "We Do Recover Shirt | Minimal Sobriety Support Unisex Tee",
            "shop_name": "IkersonLTD",
            "price": 24.99,
            "reviews": 54500,
            "rating": 5.0,
            "favorites": 42000,
            "tags": ["we do recover", "sobriety shirt", "recovery tee", "minimal recovery gift"],
        },
    ],
    "recovery": [
        {
            "title": "Recovery Definition Shirt | Addiction Recovery Dictionary Graphic Tee",
            "shop_name": "SphinxShirtCo",
            "price": 24.99,
            "reviews": 7700,
            "rating": 5.0,
            "favorites": 12000,
            "tags": ["recovery definition", "dictionary tee", "addiction recovery", "sobriety gift"],
        },
        {
            "title": "When We Recover Loudly Shirt | Sobriety Advocacy Graphic Tee",
            "shop_name": "DrawdotsLtd",
            "price": 23.60,
            "reviews": 3600,
            "rating": 4.5,
            "favorites": 5100,
            "tags": ["recover loudly", "sobriety advocacy", "recovery shirt", "awareness tee"],
        },
        {
            "title": "Recovery Crew Shirt | Mental Health Support Varsity Graphic Tee",
            "shop_name": "PersonalizedTeeWorld",
            "price": 27.90,
            "reviews": 3400,
            "rating": 5.0,
            "favorites": 4800,
            "tags": ["recovery crew", "varsity recovery", "support squad", "sobriety shirt"],
        },
        {
            "title": "1 Day At A Time Recovery Shirt | Sobriety Milestone Unisex Tee",
            "shop_name": "GlizzysGraphics",
            "price": 31.99,
            "reviews": 75,
            "rating": 5.0,
            "favorites": 890,
            "tags": ["one day at a time", "recovery shirt", "sobriety gift", "milestone tee"],
        },
    ],
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
        if key == "default" and any(
            word in lowered for word in ("sober", "sobriety", "recovery", "addiction", "milestone")
        ):
            key = "sober" if "sober" in lowered else "recovery"
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
