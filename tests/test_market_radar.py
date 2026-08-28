"""Unit tests for market_radar feeds, health scoring, and state."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from market_radar.feeds import (
    CRYPTOS,
    STOCKS,
    DemoFeedBackend,
    fear_greed_label,
    parse_coingecko_global,
    parse_coingecko_markets,
    parse_fear_greed,
    parse_stooq_csv,
)
from market_radar.state import (
    AssetQuote,
    GlobalStats,
    MarketState,
    compute_health,
    health_label,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _quote(
    symbol: str,
    *,
    kind: str = "crypto",
    price: float = 100.0,
    change: float | None = 1.0,
    mcap: float | None = 1e9,
) -> AssetQuote:
    return AssetQuote(
        symbol=symbol,
        name=symbol.title(),
        kind=kind,
        price=price,
        change_24h_pct=change,
        market_cap=mcap,
        observed_at=NOW,
    )


class FeedParserTests(unittest.TestCase):
    def test_parse_coingecko_markets(self) -> None:
        payload = [
            {
                "id": "bitcoin",
                "current_price": 97400.5,
                "price_change_percentage_24h": 2.31,
                "market_cap": 1.92e12,
                "total_volume": 4.1e10,
            },
            {"id": "not-tracked", "current_price": 1.0},
            {"id": "ethereum", "current_price": None},
        ]
        quotes = parse_coingecko_markets(payload, NOW)
        self.assertEqual(len(quotes), 1)
        btc = quotes[0]
        self.assertEqual(btc.symbol, "BTC")
        self.assertEqual(btc.kind, "crypto")
        self.assertAlmostEqual(btc.price, 97400.5)
        self.assertAlmostEqual(btc.change_24h_pct or 0, 2.31)

    def test_parse_coingecko_global(self) -> None:
        payload = {
            "data": {
                "total_market_cap": {"usd": 3.4e12, "eur": 3.1e12},
                "market_cap_percentage": {"btc": 56.4, "eth": 12.1},
            }
        }
        total, dominance = parse_coingecko_global(payload)
        self.assertAlmostEqual(total or 0, 3.4e12)
        self.assertAlmostEqual(dominance or 0, 56.4)

    def test_parse_fear_greed(self) -> None:
        value, label = parse_fear_greed(
            {"data": [{"value": "61", "value_classification": "Greed"}]}
        )
        self.assertEqual(value, 61)
        self.assertEqual(label, "Greed")
        self.assertEqual(parse_fear_greed({"data": []}), (None, None))

    def test_parse_stooq_csv(self) -> None:
        text = (
            "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            "SPY.US,2026-08-28,21:59:57,600.00,606.00,599.00,603.00,51231234\n"
            "NVDA.US,2026-08-28,21:59:57,140.00,142.50,138.00,139.30,90123456\n"
            "BOGUS.US,N/D,N/D,N/D,N/D,N/D,N/D,N/D\n"
        )
        quotes = parse_stooq_csv(text, NOW)
        self.assertEqual({q.symbol for q in quotes}, {"SPY", "NVDA"})
        spy = next(q for q in quotes if q.symbol == "SPY")
        self.assertEqual(spy.kind, "index")
        self.assertAlmostEqual(spy.price, 603.0)
        self.assertAlmostEqual(spy.change_24h_pct or 0, 0.5)
        nvda = next(q for q in quotes if q.symbol == "NVDA")
        self.assertLess(nvda.change_24h_pct or 0, 0)

    def test_fear_greed_label_bands(self) -> None:
        self.assertEqual(fear_greed_label(10), "Extreme Fear")
        self.assertEqual(fear_greed_label(50), "Neutral")
        self.assertEqual(fear_greed_label(90), "Extreme Greed")


class HealthScoreTests(unittest.TestCase):
    def test_everything_up_scores_high(self) -> None:
        quotes = [
            _quote("BTC", change=4.0),
            _quote("ETH", change=6.0),
            _quote("SPY", kind="index", change=1.2),
        ]
        stats = GlobalStats(fear_greed_value=70)
        health = compute_health(quotes, stats)
        self.assertIsNotNone(health["score"])
        self.assertGreater(health["score"], 70)
        self.assertEqual(health["components"]["breadth"], 100.0)

    def test_selloff_scores_low_and_labels_risk_off(self) -> None:
        quotes = [
            _quote("BTC", change=-8.0),
            _quote("ETH", change=-12.0),
            _quote("SPY", kind="index", change=-3.0),
        ]
        stats = GlobalStats(fear_greed_value=15)
        health = compute_health(quotes, stats)
        self.assertLess(health["score"], 30)
        self.assertIn(health["label"], {"risk-off", "severe risk-off"})

    def test_missing_components_renormalize(self) -> None:
        health = compute_health([_quote("BTC", change=2.0)], None)
        self.assertIsNotNone(health["score"])
        self.assertIsNone(health["components"]["stocks"])
        self.assertIsNone(health["components"]["sentiment"])

    def test_no_data_yields_unknown(self) -> None:
        health = compute_health([], None)
        self.assertIsNone(health["score"])
        self.assertEqual(health["label"], "unknown")
        self.assertEqual(health_label(None), "unknown")


class MarketStateTests(unittest.TestCase):
    def test_mover_event_fires_once_per_direction(self) -> None:
        state = MarketState(data_source="demo")

        async def scenario() -> tuple[list, list, list]:
            first = await state.ingest_cycle([_quote("SOL", change=7.5)])
            second = await state.ingest_cycle([_quote("SOL", change=8.0)])
            third = await state.ingest_cycle([_quote("SOL", change=-6.0)])
            return first, second, third

        first, second, third = asyncio.run(scenario())
        self.assertEqual([e["type"] for e in first if e["symbol"] == "SOL"], ["mover-up"])
        self.assertEqual([e for e in second if e["symbol"] == "SOL"], [])
        self.assertEqual([e["type"] for e in third if e["symbol"] == "SOL"], ["mover-down"])

    def test_risk_off_alarm_fires_and_clears(self) -> None:
        state = MarketState(data_source="demo")
        crash = [_quote(s, change=-10.0) for s in ("BTC", "ETH", "SOL")]
        recovery = [_quote(s, change=3.0) for s in ("BTC", "ETH", "SOL")]

        async def scenario() -> tuple[list, list, dict]:
            crash_events = await state.ingest_cycle(crash, GlobalStats(fear_greed_value=10))
            recover_events = await state.ingest_cycle(recovery, GlobalStats(fear_greed_value=60))
            return crash_events, recover_events, await state.snapshot()

        crash_events, recover_events, snapshot = asyncio.run(scenario())
        self.assertIn("risk-off-alarm", [e["type"] for e in crash_events])
        self.assertTrue(any(e["alarm"] for e in crash_events))
        self.assertIn("alarm-cleared", [e["type"] for e in recover_events])
        self.assertFalse(snapshot["alarm_active"])

    def test_snapshot_shape(self) -> None:
        state = MarketState(data_source="live")

        async def scenario() -> dict:
            await state.ingest_cycle(
                [
                    _quote("BTC", change=2.0, price=97000.0, mcap=1.9e12),
                    _quote("ETH", change=-1.0, price=3400.0, mcap=4.1e11),
                    _quote("SPY", kind="index", change=0.4, price=600.0, mcap=None),
                ],
                GlobalStats(
                    total_market_cap_usd=3.4e12,
                    btc_dominance_pct=56.0,
                    fear_greed_value=61,
                    fear_greed_label="Greed",
                ),
            )
            return await state.snapshot()

        snapshot = asyncio.run(scenario())
        self.assertEqual(snapshot["data_source"], "live")
        self.assertEqual([c["symbol"] for c in snapshot["cryptos"]], ["BTC", "ETH"])
        self.assertEqual([s["symbol"] for s in snapshot["stocks"]], ["SPY"])
        self.assertEqual(snapshot["global"]["btc_dominance_pct"], 56.0)
        self.assertEqual(len(snapshot["history"]), 1)
        self.assertEqual(snapshot["history"][0]["btc_price"], 97000.0)
        self.assertTrue(snapshot["top_movers"])
        self.assertIsNotNone(snapshot["health"]["score"])

    def test_session_range_tracks_extremes(self) -> None:
        state = MarketState()

        async def scenario() -> dict:
            await state.ingest_cycle([_quote("BTC", price=100.0)])
            await state.ingest_cycle([_quote("BTC", price=120.0)])
            await state.ingest_cycle([_quote("BTC", price=90.0)])
            return await state.snapshot()

        snapshot = asyncio.run(scenario())
        btc = snapshot["cryptos"][0]
        self.assertEqual(btc["session_high"], 120.0)
        self.assertEqual(btc["session_low"], 90.0)
        self.assertEqual(btc["price_history"], [100.0, 120.0, 90.0])


class DemoFeedTests(unittest.TestCase):
    def test_demo_covers_full_universe(self) -> None:
        backend = DemoFeedBackend(MarketState(data_source="demo"))
        quotes, stats = backend.generate_cycle(1)
        self.assertEqual(len(quotes), len(CRYPTOS) + len(STOCKS))
        self.assertTrue(all(q.price > 0 for q in quotes))
        self.assertIsNotNone(stats.btc_dominance_pct)
        self.assertIsNotNone(stats.fear_greed_value)

    def test_shock_drops_altcoins_and_sentiment(self) -> None:
        backend = DemoFeedBackend(MarketState(data_source="demo"))
        before = {q.symbol: q.price for q, _ in [(q, None) for q in backend.generate_cycle(1)[0]]}
        for tick in range(2, backend.shock_at):
            backend.generate_cycle(tick)
        shocked, stats = backend.generate_cycle(backend.shock_at)
        eth = next(q for q in shocked if q.symbol == "ETH")
        self.assertLess(eth.price, before["ETH"])
        self.assertLessEqual(stats.fear_greed_value or 100, 30)

    def test_health_recovers_after_rally(self) -> None:
        state = MarketState(data_source="demo")
        backend = DemoFeedBackend(state)

        async def scenario() -> tuple[float, float]:
            shock_score = rally_score = 0.0
            for tick in range(1, backend.rally_at + 12):
                quotes, stats = backend.generate_cycle(tick)
                await state.ingest_cycle(quotes, stats)
                snapshot = await state.snapshot()
                if tick == backend.shock_at + 2:
                    shock_score = snapshot["health"]["score"]
                if tick == backend.rally_at + 11:
                    rally_score = snapshot["health"]["score"]
            return shock_score, rally_score

        shock_score, rally_score = asyncio.run(scenario())
        self.assertLess(shock_score, 45)
        self.assertGreater(rally_score, shock_score)


if __name__ == "__main__":
    unittest.main()
