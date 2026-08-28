"""In-memory market quotes, history, and dashboard snapshot state."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .health import compute_health


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass
class QuoteUpdate:
    symbol: str
    name: str
    asset_class: str
    price: float
    change_pct_24h: float | None = None
    market_cap_usd: float | None = None
    volume_24h_usd: float | None = None
    category: str | None = None
    rank: int | None = None
    image_url: str | None = None
    observed_at: datetime = field(default_factory=utc_now)


@dataclass
class GlobalStats:
    btc_dominance: float | None = None
    eth_dominance: float | None = None
    total_market_cap_usd: float | None = None
    total_volume_24h_usd: float | None = None
    market_cap_change_24h_pct: float | None = None
    active_cryptocurrencies: int | None = None
    observed_at: datetime = field(default_factory=utc_now)


@dataclass
class MarketState:
    history_len: int = 120

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cryptos: dict[str, dict[str, Any]] = {}
        self._stocks: dict[str, dict[str, Any]] = {}
        self._crypto_history: dict[str, deque[float]] = {}
        self._stock_history: dict[str, deque[float]] = {}
        self._global: GlobalStats | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._source = "initializing"
        self._last_poll: datetime | None = None
        self._poll_count = 0

    async def add_system_event(self, kind: str, message: str) -> None:
        async with self._lock:
            self._events.appendleft(
                {
                    "type": kind,
                    "message": message,
                    "at": iso_time(utc_now()),
                }
            )

    async def set_source(self, source: str) -> None:
        async with self._lock:
            self._source = source

    async def ingest_global(self, stats: GlobalStats) -> None:
        async with self._lock:
            self._global = stats

    async def ingest_quotes(self, quotes: list[QuoteUpdate]) -> None:
        async with self._lock:
            now = utc_now()
            self._last_poll = now
            self._poll_count += 1
            for quote in quotes:
                payload = {
                    "symbol": quote.symbol,
                    "name": quote.name,
                    "asset_class": quote.asset_class,
                    "price": quote.price,
                    "change_pct_24h": quote.change_pct_24h,
                    "market_cap_usd": quote.market_cap_usd,
                    "volume_24h_usd": quote.volume_24h_usd,
                    "category": quote.category,
                    "rank": quote.rank,
                    "image_url": quote.image_url,
                    "updated_at": iso_time(quote.observed_at),
                }
                if quote.asset_class == "crypto":
                    self._cryptos[quote.symbol] = payload
                    history = self._crypto_history.setdefault(quote.symbol, deque(maxlen=self.history_len))
                else:
                    self._stocks[quote.symbol] = payload
                    history = self._stock_history.setdefault(quote.symbol, deque(maxlen=self.history_len))
                history.append(quote.price)

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            cryptos = sorted(
                self._cryptos.values(),
                key=lambda item: (item.get("rank") is None, item.get("rank") or 9999, item["symbol"]),
            )
            stocks = sorted(self._stocks.values(), key=lambda item: item["symbol"])
            global_stats = None
            if self._global is not None:
                global_stats = {
                    "btc_dominance": self._global.btc_dominance,
                    "eth_dominance": self._global.eth_dominance,
                    "total_market_cap_usd": self._global.total_market_cap_usd,
                    "total_volume_24h_usd": self._global.total_volume_24h_usd,
                    "market_cap_change_24h_pct": self._global.market_cap_change_24h_pct,
                    "active_cryptocurrencies": self._global.active_cryptocurrencies,
                    "updated_at": iso_time(self._global.observed_at),
                }
            health = compute_health(cryptos=cryptos, stocks=stocks, global_stats=global_stats)
            btc = self._cryptos.get("bitcoin")
            return {
                "source": self._source,
                "poll_count": self._poll_count,
                "updated_at": iso_time(self._last_poll) if self._last_poll else None,
                "bitcoin": btc,
                "cryptos": cryptos,
                "stocks": stocks,
                "global": global_stats,
                "health": health,
                "history": {
                    "crypto": {symbol: list(values) for symbol, values in self._crypto_history.items()},
                    "stocks": {symbol: list(values) for symbol, values in self._stock_history.items()},
                },
                "events": list(self._events),
            }
