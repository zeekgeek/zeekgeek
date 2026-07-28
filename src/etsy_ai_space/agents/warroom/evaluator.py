"""Warroom agent — future: deactivate underperforming listings (human approval required)."""

from __future__ import annotations

from typing import Any


def evaluate_listing_performance(metrics: dict[str, Any]) -> dict[str, Any]:
    """Placeholder scoring for Phase 5+ shop optimization."""
    views = int(metrics.get("views") or 0)
    favorites = int(metrics.get("favorites") or 0)
    sales = int(metrics.get("sales") or 0)
    recommendation = "hold"
    if views > 200 and sales == 0 and favorites < 3:
        recommendation = "review_for_removal"
    return {
        "recommendation": recommendation,
        "views": views,
        "favorites": favorites,
        "sales": sales,
        "note": "Warroom never auto-deletes in safe mode — export a report for manual action.",
    }
