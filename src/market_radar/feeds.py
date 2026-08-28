"""Live and demo market data backends."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from .state import GlobalStats, MarketState, QuoteUpdate
from .symbols import CRYPTO_PER_PAGE, STOCK_WATCHLIST

LOGGER = logging.getLogger(__name__)

USER_AGENT = "market-radar/0.1"
COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
YAHOO_CHART = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"


class FeedBackend(Protocol):
    async def run(self) -> None:
        """Poll market data until cancelled."""


def _fetch_json(url: str, *, timeout: float = 25.0) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass
class LiveFeedBackend:
    state: MarketState
    interval: float = 45.0
    crypto_per_page: int = CRYPTO_PER_PAGE
    request_timeout: float = 25.0

    async def run(self) -> None:
        await self.state.set_source("live")
        await self._poll_once()
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self._poll_once()
            except Exception as exc:
                LOGGER.warning("Market poll failed (%s)", exc)
                await self.state.add_system_event("poll-error", f"Market poll failed: {exc}")

    async def _poll_once(self) -> None:
        crypto_task = asyncio.to_thread(self._fetch_crypto)
        global_task = asyncio.to_thread(self._fetch_global)
        stock_task = asyncio.to_thread(self._fetch_stocks)
        crypto_quotes, global_stats, stock_quotes = await asyncio.gather(crypto_task, global_task, stock_task)
        await self.state.ingest_global(global_stats)
        await self.state.ingest_quotes(crypto_quotes + stock_quotes)

    def _fetch_crypto(self) -> list[QuoteUpdate]:
        params = urllib.parse.urlencode(
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": self.crypto_per_page,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h",
            }
        )
        payload = _fetch_json(f"{COINGECKO_MARKETS}?{params}", timeout=self.request_timeout)
        now = datetime.now(UTC)
        quotes: list[QuoteUpdate] = []
        for index, row in enumerate(payload, start=1):
            quotes.append(
                QuoteUpdate(
                    symbol=row["id"],
                    name=row["name"],
                    asset_class="crypto",
                    price=float(row["current_price"]),
                    change_pct_24h=row.get("price_change_percentage_24h"),
                    market_cap_usd=row.get("market_cap"),
                    volume_24h_usd=row.get("total_volume"),
                    rank=index,
                    image_url=row.get("image"),
                    observed_at=now,
                )
            )
        return quotes

    def _fetch_global(self) -> GlobalStats:
        payload = _fetch_json(COINGECKO_GLOBAL, timeout=self.request_timeout)
        data = payload.get("data", {})
        now = datetime.now(UTC)
        return GlobalStats(
            btc_dominance=(data.get("market_cap_percentage") or {}).get("btc"),
            eth_dominance=(data.get("market_cap_percentage") or {}).get("eth"),
            total_market_cap_usd=(data.get("total_market_cap") or {}).get("usd"),
            total_volume_24h_usd=(data.get("total_volume") or {}).get("usd"),
            market_cap_change_24h_pct=(data.get("market_cap_change_percentage_24h_usd")),
            active_cryptocurrencies=data.get("active_cryptocurrencies"),
            observed_at=now,
        )

    def _fetch_stocks(self) -> list[QuoteUpdate]:
        quotes: list[QuoteUpdate] = []
        now = datetime.now(UTC)
        for entry in STOCK_WATCHLIST:
            encoded = urllib.parse.quote(entry.symbol, safe="")
            url = YAHOO_CHART.format(symbol=encoded) + "?interval=1d&range=5d"
            payload = _fetch_json(url, timeout=self.request_timeout)
            result = (payload.get("chart") or {}).get("result") or []
            if not result:
                continue
            meta = result[0].get("meta") or {}
            price = meta.get("regularMarketPrice")
            if price is None:
                continue
            previous = meta.get("chartPreviousClose") or meta.get("previousClose")
            change_pct = None
            if previous:
                change_pct = round(((float(price) - float(previous)) / float(previous)) * 100.0, 2)
            quotes.append(
                QuoteUpdate(
                    symbol=entry.symbol,
                    name=meta.get("shortName") or entry.label,
                    asset_class="stock",
                    price=float(price),
                    change_pct_24h=change_pct,
                    category=entry.category,
                    observed_at=now,
                )
            )
        return quotes


@dataclass
class DemoFeedBackend:
    state: MarketState
    interval: float = 3.0
    seed: int = 42

    _crypto_bases: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _stock_bases: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _rng: random.Random = field(init=False, repr=False)
    _cycle: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._crypto_bases = {
            "bitcoin": {"name": "Bitcoin", "price": 79500.0, "rank": 1},
            "ethereum": {"name": "Ethereum", "price": 2510.0, "rank": 2},
            "tether": {"name": "Tether", "price": 1.0, "rank": 3},
            "solana": {"name": "Solana", "price": 106.0, "rank": 4},
            "binancecoin": {"name": "BNB", "price": 590.0, "rank": 5},
            "ripple": {"name": "XRP", "price": 0.62, "rank": 6},
            "cardano": {"name": "Cardano", "price": 0.48, "rank": 7},
            "dogecoin": {"name": "Dogecoin", "price": 0.14, "rank": 8},
            "avalanche-2": {"name": "Avalanche", "price": 28.5, "rank": 9},
            "chainlink": {"name": "Chainlink", "price": 14.2, "rank": 10},
        }
        self._stock_bases = {
            entry.symbol: {"name": entry.label, "price": price, "category": entry.category}
            for entry, price in zip(
                STOCK_WATCHLIST,
                [774.0, 723.0, 537.0, 298.0, 14.5, 320.0, 516.0, 225.0, 419.0, 83.0],
                strict=True,
            )
        }

    async def run(self) -> None:
        await self.state.set_source("demo")
        await self.state.add_system_event(
            "demo-mode",
            "Simulated crypto + equity quotes (use live mode for CoinGecko / Yahoo Finance).",
        )
        while True:
            await self._poll_once()
            await asyncio.sleep(self.interval)

    async def _poll_once(self) -> None:
        self._cycle += 1
        now = datetime.now(UTC)
        market_drift = math.sin(self._cycle / 18.0) * 0.35 + self._rng.uniform(-0.25, 0.25)
        quotes: list[QuoteUpdate] = []

        for symbol, base in self._crypto_bases.items():
            volatility = 0.004 if symbol == "tether" else 0.012
            move = market_drift * 0.6 + self._rng.gauss(0, volatility)
            base["price"] = max(0.0001, base["price"] * (1.0 + move))
            change = market_drift * 2.2 + self._rng.uniform(-2.5, 2.5)
            quotes.append(
                QuoteUpdate(
                    symbol=symbol,
                    name=base["name"],
                    asset_class="crypto",
                    price=round(base["price"], 4 if base["price"] < 10 else 2),
                    change_pct_24h=round(change, 2),
                    market_cap_usd=base["price"] * self._rng.uniform(8e6, 2.1e8),
                    volume_24h_usd=base["price"] * self._rng.uniform(1e5, 5e6),
                    rank=base["rank"],
                    observed_at=now,
                )
            )

        for symbol, base in self._stock_bases.items():
            if symbol == "^VIX":
                move = -market_drift * 0.08 + self._rng.gauss(0, 0.02)
            else:
                move = market_drift * 0.0015 + self._rng.gauss(0, 0.0018)
            base["price"] = max(0.01, base["price"] * (1.0 + move))
            change = market_drift * 1.4 + self._rng.uniform(-1.2, 1.2)
            if symbol == "^VIX":
                change = -market_drift * 3.5 + self._rng.uniform(-2.0, 2.0)
            quotes.append(
                QuoteUpdate(
                    symbol=symbol,
                    name=base["name"],
                    asset_class="stock",
                    price=round(base["price"], 2),
                    change_pct_24h=round(change, 2),
                    category=base["category"],
                    observed_at=now,
                )
            )

        btc_price = self._crypto_bases["bitcoin"]["price"]
        total_mcap = btc_price * 20_000_000
        await self.state.ingest_global(
            GlobalStats(
                btc_dominance=round(52.0 + market_drift * 0.4, 2),
                eth_dominance=round(16.5 - market_drift * 0.2, 2),
                total_market_cap_usd=total_mcap,
                total_volume_24h_usd=total_mcap * 0.08,
                market_cap_change_24h_pct=round(market_drift * 2.8, 2),
                active_cryptocurrencies=19360,
                observed_at=now,
            )
        )
        await self.state.ingest_quotes(quotes)
