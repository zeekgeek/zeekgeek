"""Scoring heuristics for trend listings."""

from __future__ import annotations

from .models import ScrapedListing


def score_listing(
    listing: ScrapedListing,
    *,
    price_weight: float = 0.15,
    reviews_weight: float = 0.35,
    favorites_weight: float = 0.30,
    rating_weight: float = 0.20,
) -> float:
    """Compute a 0–100 performance score from observable Etsy signals."""
    reviews = min(listing.review_count or 0, 5000) / 5000.0
    favorites = min(listing.favorites or 0, 10000) / 10000.0
    rating = (listing.rating or 0.0) / 5.0

    price_signal = 0.5
    if listing.price_amount is not None:
        # Mid-market POD shirts often land $18–$28; peak around $22.
        target = 22.0
        distance = abs(listing.price_amount - target)
        price_signal = max(0.0, 1.0 - (distance / 20.0))

    score = (
        reviews * reviews_weight
        + favorites * favorites_weight
        + rating * rating_weight
        + price_signal * price_weight
    ) * 100.0
    listing.performance_score = round(score, 2)
    return listing.performance_score
