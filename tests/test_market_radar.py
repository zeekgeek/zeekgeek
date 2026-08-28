"""Unit tests for market_radar health scoring and state."""

from __future__ import annotations

import asyncio
import unittest

from market_radar.health import compute_health
from market_radar.state import GlobalStats, MarketState, QuoteUpdate
from market_radar.web import create_app


class HealthTests(unittest.TestCase):
    def test_risk_on_when_breadth_high(self) -> None:
        cryptos = [{"change_pct_24h": 2.0}, {"change_pct_24h": 1.5}, {"change_pct_24h": 0.8}]
        stocks = [{"symbol": "SPY", "change_pct_24h": 1.1}, {"symbol": "^VIX", "price": 14.0, "change_pct_24h": -3.0}]
        health = compute_health(
            cryptos=cryptos,
            stocks=stocks,
            global_stats={"btc_dominance": 52.0, "market_cap_change_24h_pct": 1.8},
        )
        self.assertGreaterEqual(health["score"], 60)
        self.assertEqual(health["posture"], "risk-on")

    def test_risk_off_when_volatility_elevated(self) -> None:
        cryptos = [{"change_pct_24h": -3.0}, {"change_pct_24h": -2.5}]
        stocks = [{"symbol": "SPY", "change_pct_24h": -1.8}, {"symbol": "^VIX", "price": 32.0, "change_pct_24h": 12.0}]
        health = compute_health(
            cryptos=cryptos,
            stocks=stocks,
            global_stats={"btc_dominance": 55.0, "market_cap_change_24h_pct": -4.0},
        )
        self.assertLess(health["score"], 45)
        self.assertEqual(health["posture"], "risk-off")
        self.assertEqual(health["vix_regime"], "fearful")


class StateTests(unittest.TestCase):
    def test_ingest_and_snapshot(self) -> None:
        asyncio.run(self._flow())

    async def _flow(self) -> None:
        state = MarketState(history_len=10)
        await state.ingest_quotes(
            [
                QuoteUpdate(symbol="bitcoin", name="Bitcoin", asset_class="crypto", price=80000, change_pct_24h=1.2, rank=1),
                QuoteUpdate(symbol="SPY", name="S&P 500", asset_class="stock", price=500, change_pct_24h=0.5, category="index"),
            ]
        )
        await state.ingest_global(GlobalStats(btc_dominance=52.0, total_market_cap_usd=2.5e12))
        snap = await state.snapshot()
        self.assertEqual(snap["bitcoin"]["price"], 80000)
        self.assertEqual(len(snap["cryptos"]), 1)
        self.assertEqual(len(snap["stocks"]), 1)
        self.assertIn("score", snap["health"])
        self.assertIn("bitcoin", snap["history"]["crypto"])


class WebRouteTests(unittest.TestCase):
    def test_routes_exist(self) -> None:
        from fastapi.routing import APIRoute

        app = create_app(MarketState())
        paths = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes if isinstance(route, APIRoute)}
        self.assertIn(("/api/market", ("GET",)), paths)
        self.assertIn(("/api/events", ("GET",)), paths)


if __name__ == "__main__":
    unittest.main()
