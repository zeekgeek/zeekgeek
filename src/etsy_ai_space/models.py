"""Shared dataclasses for scraped listings, trends, and export bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds")


@dataclass
class ScrapedListing:
    """One Etsy listing observation from a trend scrape."""

    title: str
    url: str
    etsy_listing_id: str | None = None
    price_amount: float | None = None
    price_currency: str = "USD"
    tags: list[str] = field(default_factory=list)
    shop_name: str | None = None
    review_count: int | None = None
    rating: float | None = None
    favorites: int | None = None
    scraped_at: datetime = field(default_factory=utc_now)
    performance_score: float | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "etsy_listing_id": self.etsy_listing_id,
            "title": self.title,
            "price_amount": self.price_amount,
            "price_currency": self.price_currency,
            "tags": self.tags,
            "shop_name": self.shop_name,
            "review_count": self.review_count,
            "rating": self.rating,
            "favorites": self.favorites,
            "url": self.url,
            "scraped_at": iso_time(self.scraped_at),
            "performance_score": self.performance_score,
        }


@dataclass
class ScrapeRun:
    """Metadata for one researcher scrape session."""

    query: str
    source: str
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    listing_count: int = 0
    status: str = "running"
    id: int | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "query": self.query,
            "source": self.source,
            "started_at": iso_time(self.started_at),
            "finished_at": iso_time(self.finished_at) if self.finished_at else None,
            "listing_count": self.listing_count,
            "status": self.status,
        }


@dataclass
class CreativeBrief:
    """Phase 2 output — trend-informed design direction."""

    trend_summary: str
    niche: str
    target_buyer: str
    design_direction: str
    color_palette: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    reference_listing_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    status: str = "draft"
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trend_summary": self.trend_summary,
            "niche": self.niche,
            "target_buyer": self.target_buyer,
            "design_direction": self.design_direction,
            "color_palette": self.color_palette,
            "avoid": self.avoid,
            "reference_listing_ids": self.reference_listing_ids,
            "created_at": iso_time(self.created_at),
            "status": self.status,
        }


@dataclass
class ListingDraft:
    """Phase 3–4 output ready for manual Etsy upload."""

    title: str
    description: str
    tags: list[str]
    price: float
    image_prompt: str
    image_path: str | None = None
    taxonomy_hint: str | None = None
    brief_id: int | None = None
    created_at: datetime = field(default_factory=utc_now)
    status: str = "pending_review"
    id: int | None = None

    def to_export_row(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "tags": "|".join(self.tags),
            "price": self.price,
            "image_prompt": self.image_prompt,
            "image_path": self.image_path or "",
            "taxonomy_hint": self.taxonomy_hint or "",
            "status": self.status,
        }
