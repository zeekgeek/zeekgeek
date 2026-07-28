"""Import BrowserClaw JSON research output into SQLite."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from ..db import StoreDatabase, default_db_path
from ..models import ScrapedListing
from ..scoring import score_listing


def import_browserclaw_json(path: Path, db: StoreDatabase, *, min_score: float = 35.0) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    query = str(payload.get("query") or "unknown")
    run = db.start_scrape_run(query=query, source="browserclaw")
    assert run.id is not None

    listings: list[ScrapedListing] = []
    scraped_at = datetime.now(UTC)
    for row in payload.get("listings") or []:
        item = ScrapedListing(
            etsy_listing_id=row.get("etsyListingId"),
            title=str(row.get("title") or ""),
            url=str(row.get("url") or ""),
            price_amount=row.get("priceAmount"),
            shop_name=row.get("shopName"),
            review_count=row.get("reviewCount"),
            rating=row.get("rating"),
            scraped_at=scraped_at,
        )
        score_listing(item)
        listings.append(item)

    kept = [item for item in listings if (item.performance_score or 0.0) >= min_score]
    stored = db.insert_listings(run.id, kept)
    db.finish_scrape_run(run.id, listing_count=stored, status="completed")
    return {"run_id": run.id, "query": query, "scraped": len(listings), "stored": stored}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import BrowserClaw Etsy JSON into SQLite")
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--min-score", type=float, default=35.0)
    args = parser.parse_args()
    db = StoreDatabase(args.db or default_db_path())
    result = import_browserclaw_json(args.json_path, db, min_score=args.min_score)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
