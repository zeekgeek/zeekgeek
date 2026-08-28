"""Unit tests for the Bitcoin market radar."""

from __future__ import annotations

import socket
import unittest
from datetime import UTC, datetime

from btc_radar.__main__ import pick_available_port
from btc_radar.feed import (
    DemoFeed,
    Quote,
    parse_coingecko_global,
    parse_coingecko_markets,
    parse_fear_greed,
    parse_yahoo_chart,
)
from btc_radar.health import (
    HealthInputs,
    crypto_breadth,
    detect_events,
    fear_greed_band,
    halving_countdown,
    regime_label,
    same_day_divergence,
    scale,
    score_market,
)
from btc_radar.state import MarketState
from btc_radar.universe import EQUITIES, equity_by_symbol


class HealthTests(unittest.TestCase):
    def test_scale_and_regime(self) -> None:
        self.assertEqual(scale(None, -8, 8), None)
        self.assertEqual(scale(0, -8, 8), 50.0)
        self.assertEqual(scale(8, -8, 8), 100.0)
        self.assertEqual(scale(-8, -8, 8), 0.0)
        self.assertEqual(regime_label(80), "risk-on")
        self.assertEqual(regime_label(20), "risk-off")
        self.assertEqual(regime_label(50), "mixed")
        self.assertEqual(regime_label(None), "unknown")

    def test_breadth_and_divergence(self) -> None:
        breadth = crypto_breadth([2.0, 1.1, -0.8, 0.01, None])
        self.assertEqual(breadth["green"], 2)
        self.assertEqual(breadth["red"], 1)
        self.assertEqual(breadth["n"], 4)
        self.assertEqual(same_day_divergence(1.2, -0.7), "crypto-led")
        self.assertEqual(same_day_divergence(-1.2, 0.7), "equities-led")
        self.assertEqual(same_day_divergence(1.2, 0.7), "risk-on-together")
        self.assertIsNone(same_day_divergence(0.1, -0.1))

    def test_risk_on_score(self) -> None:
        health = score_market(
            HealthInputs(
                fear_greed=78,
                breadth_pct_green=80,
                btc_change_24h=4.5,
                spy_change_24h=1.1,
                vix=13.5,
                btc_change_7d=2.0,
                alt_changes_7d=(9.0, 8.0, 7.0),
                btc_dominance=51.0,
            )
        )
        self.assertEqual(health["regime"], "risk-on")
        self.assertGreater(health["score"], 62)
        self.assertEqual(health["altseason"]["label"], "altseason")
        self.assertEqual(health["fear_greed_band"], "greed")

    def test_risk_off_score_and_events(self) -> None:
        health = score_market(
            HealthInputs(
                fear_greed=12,
                breadth_pct_green=10,
                btc_change_24h=-6.2,
                spy_change_24h=-1.8,
                vix=28.0,
            )
        )
        self.assertEqual(health["regime"], "risk-off")
        events = detect_events(
            previous_regime="risk-on",
            health=health,
            btc_change_24h=-6.2,
            vix=28.0,
            fear_greed=12,
            movers=[("SOL", -9.4)],
        )
        kinds = {event["kind"] for event in events}
        self.assertIn("regime-shift", kinds)
        self.assertIn("btc-move", kinds)
        self.assertIn("vix-spike", kinds)
        self.assertIn("sentiment", kinds)
        self.assertIn("mover", kinds)

    def test_halving_and_bands(self) -> None:
        clock = datetime(2026, 8, 28, tzinfo=UTC)
        count = halving_countdown(clock)
        self.assertFalse(count["past"])
        self.assertGreater(count["days"], 500)
        self.assertEqual(fear_greed_band(15), "extreme-fear")
        self.assertEqual(fear_greed_band(90), "extreme-greed")


class ParserTests(unittest.TestCase):
    def test_coingecko_markets(self) -> None:
        quotes = parse_coingecko_markets(
            [
                {
                    "id": "bitcoin",
                    "symbol": "btc",
                    "name": "Bitcoin",
                    "current_price": 100000,
                    "market_cap": 2e12,
                    "total_volume": 4e10,
                    "market_cap_rank": 1,
                    "price_change_percentage_1h_in_currency": 0.2,
                    "price_change_percentage_24h_in_currency": 1.5,
                    "price_change_percentage_7d_in_currency": 3.0,
                    "sparkline_in_7d": {"price": [99_000, 100_000, 101_000]},
                },
                {"id": "not-tracked", "current_price": 1},
            ]
        )
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].symbol, "BTC")
        self.assertEqual(quotes[0].price, 100000)
        self.assertEqual(quotes[0].change_24h, 1.5)
        self.assertEqual(quotes[0].sparkline, [99_000.0, 100_000.0, 101_000.0])

    def test_global_fng_yahoo(self) -> None:
        glob = parse_coingecko_global(
            {
                "data": {
                    "total_market_cap": {"usd": 3.2e12},
                    "total_volume": {"usd": 1.1e11},
                    "market_cap_percentage": {"btc": 54.2, "eth": 13.9},
                    "market_cap_change_percentage_24h_usd": 1.25,
                }
            }
        )
        self.assertEqual(glob["btc_dominance"], 54.2)
        value, label = parse_fear_greed({"data": [{"value": "42", "value_classification": "Fear"}]})
        self.assertEqual(value, 42.0)
        self.assertEqual(label, "Fear")
        spy = equity_by_symbol("SPY")
        assert spy is not None
        quote = parse_yahoo_chart(
            {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 560.0,
                                "previousClose": 550.0,
                                "chartPreviousClose": 550.0,
                            },
                            "indicators": {"quote": [{"close": [548.0, 552.0, 560.0]}]},
                        }
                    ]
                }
            },
            spy,
        )
        self.assertEqual(quote.symbol, "SPY")
        self.assertAlmostEqual(quote.change_24h or 0, 100.0 * (560 / 550 - 1), places=4)
        self.assertEqual(quote.sparkline[-1], 560.0)


class DemoAndStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_snapshot_has_board_and_health(self) -> None:
        feed = DemoFeed()
        raw = await feed.fetch()
        self.assertEqual(raw.source, "demo")
        self.assertTrue(any(quote.symbol == "BTC" and quote.price for quote in raw.cryptos))
        self.assertTrue(any(quote.symbol == "SPY" for quote in raw.equities))
        self.assertIsNotNone(raw.fear_greed)
        state = MarketState()
        await state.ingest(raw, mode="demo")
        snap = await state.snapshot()
        self.assertEqual(snap["mode"], "demo")
        self.assertEqual(snap["bitcoin"]["symbol"], "BTC")
        self.assertGreaterEqual(len(snap["cryptos"]), 8)
        self.assertGreaterEqual(len(snap["equities"]["indices"]), 4)
        self.assertGreaterEqual(len(snap["equities"]["mega"]), 5)
        self.assertIn("VIX", [row["symbol"] for row in snap["equities"]["macro"]])
        self.assertIn(snap["health"]["regime"], {"risk-on", "risk-off", "mixed", "unknown"})
        self.assertTrue(snap["roadmap"])
        self.assertIn("days", snap["halving"])
        self.assertTrue(snap["stables"])

    async def test_demo_risk_off_episode_emits_events(self) -> None:
        feed = DemoFeed()
        state = MarketState()
        for _ in range(75):
            await state.ingest(await feed.fetch(), mode="demo")
        snap = await state.snapshot()
        kinds = {event["kind"] for event in snap["events"]}
        self.assertTrue(kinds.intersection({"regime-shift", "btc-move", "vix-spike", "sentiment", "divergence"}))

    async def test_system_event(self) -> None:
        state = MarketState()
        await state.add_system_event("feed-fallback", "CoinGecko 429")
        snap = await state.snapshot()
        self.assertEqual(snap["events"][0]["kind"], "feed-fallback")

    async def test_demo_prices_stay_anchored_after_many_ticks(self) -> None:
        feed = DemoFeed()
        snap = None
        for _ in range(220):
            snap = await feed.fetch()
        assert snap is not None
        btc = snap.btc()
        spy = snap.equity("SPY")
        assert btc is not None and btc.price is not None
        assert spy is not None and spy.price is not None
        self.assertGreater(btc.price, 85_000)
        self.assertLess(btc.price, 135_000)
        self.assertGreater(spy.price, 500)
        self.assertLess(spy.price, 640)


class MainTests(unittest.TestCase):
    def test_pick_available_port_skips_busy(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            occupied = sock.getsockname()[1]
            chosen = pick_available_port("127.0.0.1", occupied, max_tries=4)
        self.assertNotEqual(chosen, occupied)

    def test_universe_covers_health_proxies(self) -> None:
        symbols = {spec.symbol for spec in EQUITIES}
        self.assertTrue({"SPY", "QQQ", "VIX", "GLD", "UUP", "NVDA"} <= symbols)


class QuoteDictTests(unittest.TestCase):
    def test_quote_dict_trims_sparkline(self) -> None:
        quote = Quote(
            symbol="BTC",
            name="Bitcoin",
            kind="crypto",
            price=1.0,
            sparkline=list(range(200)),
        )
        payload = quote.as_dict()
        self.assertEqual(len(payload["sparkline"]), 96)


if __name__ == "__main__":
    unittest.main()
