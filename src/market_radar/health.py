"""Market health scoring from crypto breadth, equities, and macro signals."""

from __future__ import annotations

from typing import Any


def _pct_positive(items: list[dict[str, Any]]) -> float | None:
    changes = [item.get("change_pct_24h") for item in items if item.get("change_pct_24h") is not None]
    if not changes:
        return None
    positive = sum(1 for value in changes if value > 0)
    return round(100.0 * positive / len(changes), 1)


def _avg_change(items: list[dict[str, Any]]) -> float | None:
    changes = [item.get("change_pct_24h") for item in items if item.get("change_pct_24h") is not None]
    if not changes:
        return None
    return round(sum(changes) / len(changes), 2)


def _find_quote(quotes: list[dict[str, Any]], symbol: str) -> dict[str, Any] | None:
    for quote in quotes:
        if quote.get("symbol") == symbol:
            return quote
    return None


def compute_health(
    *,
    cryptos: list[dict[str, Any]],
    stocks: list[dict[str, Any]],
    global_stats: dict[str, Any] | None,
) -> dict[str, Any]:
    crypto_breadth = _pct_positive(cryptos)
    stock_breadth = _pct_positive(stocks)
    crypto_avg = _avg_change(cryptos)
    stock_avg = _avg_change(stocks)

    btc_dom = None
    total_mcap = None
    mcap_change = None
    if global_stats:
        btc_dom = global_stats.get("btc_dominance")
        total_mcap = global_stats.get("total_market_cap_usd")
        mcap_change = global_stats.get("market_cap_change_24h_pct")

    vix = _find_quote(stocks, "^VIX")
    vix_level = vix.get("price") if vix else None
    if vix_level is None:
        vix_regime = "unknown"
    elif vix_level < 15:
        vix_regime = "complacent"
    elif vix_level < 20:
        vix_regime = "calm"
    elif vix_level < 30:
        vix_regime = "elevated"
    else:
        vix_regime = "fearful"

    score = 50.0
    factors: list[str] = []

    if crypto_breadth is not None:
        score += (crypto_breadth - 50) * 0.25
        factors.append(f"crypto breadth {crypto_breadth:.0f}% green")
    if stock_breadth is not None:
        score += (stock_breadth - 50) * 0.35
        factors.append(f"equity breadth {stock_breadth:.0f}% green")
    if crypto_avg is not None:
        score += max(-8.0, min(8.0, crypto_avg * 1.5))
    if stock_avg is not None:
        score += max(-10.0, min(10.0, stock_avg * 2.0))
    if mcap_change is not None:
        score += max(-6.0, min(6.0, mcap_change * 1.2))
    if vix_level is not None:
        if vix_level < 18:
            score += 4
        elif vix_level > 25:
            score -= 8
        elif vix_level > 20:
            score -= 3

    score = max(0.0, min(100.0, round(score, 1)))
    if score >= 65:
        posture = "risk-on"
        tone = "bullish"
    elif score >= 45:
        posture = "mixed"
        tone = "neutral"
    else:
        posture = "risk-off"
        tone = "cautious"

    return {
        "score": score,
        "posture": posture,
        "tone": tone,
        "crypto_breadth_pct": crypto_breadth,
        "stock_breadth_pct": stock_breadth,
        "crypto_avg_change_pct": crypto_avg,
        "stock_avg_change_pct": stock_avg,
        "btc_dominance_pct": btc_dom,
        "total_market_cap_usd": total_mcap,
        "market_cap_change_24h_pct": mcap_change,
        "vix": vix_level,
        "vix_regime": vix_regime,
        "factors": factors,
    }
