"""Market data feeds for the crypto market radar.

Live mode polls three free, keyless sources:

- `CoinGecko <https://api.coingecko.com>`_ ``/coins/markets`` and ``/global``
  for crypto prices, 24h change, market caps, and BTC dominance
- `Stooq <https://stooq.com>`_ CSV quotes for bellwether stocks / ETFs
  (delayed; change is measured against the session open)
- `alternative.me <https://api.alternative.me/fng/>`_ for the crypto
  Fear & Greed index

Demo mode simulates a full session: a calm drift, a sharp **risk-off shock**
(altcoins and stocks sell off together while BTC dominance climbs), and a
relief rally — enough to exercise the health score, movers, and the alarm.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import random
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from .state import AssetQuote, GlobalStats, MarketState

LOGGER = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
STOOQ_BASE = "https://stooq.com/q/l/"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"

# (coingecko id, ticker, display name)
CRYPTOS: list[tuple[str, str, str]] = [
    ("bitcoin", "BTC", "Bitcoin"),
    ("ethereum", "ETH", "Ethereum"),
    ("solana", "SOL", "Solana"),
    ("ripple", "XRP", "XRP"),
    ("binancecoin", "BNB", "BNB"),
    ("cardano", "ADA", "Cardano"),
    ("dogecoin", "DOGE", "Dogecoin"),
    ("avalanche-2", "AVAX", "Avalanche"),
    ("polkadot", "DOT", "Polkadot"),
    ("chainlink", "LINK", "Chainlink"),
    ("litecoin", "LTC", "Litecoin"),
    ("tron", "TRX", "TRON"),
]

# (stooq symbol, ticker, display name, kind)
STOCKS: list[tuple[str, str, str, str]] = [
    ("spy.us", "SPY", "S&P 500 ETF", "index"),
    ("qqq.us", "QQQ", "Nasdaq 100 ETF", "index"),
    ("dia.us", "DIA", "Dow Jones ETF", "index"),
    ("nvda.us", "NVDA", "NVIDIA", "stock"),
    ("aapl.us", "AAPL", "Apple", "stock"),
    ("coin.us", "COIN", "Coinbase", "stock"),
    ("mstr.us", "MSTR", "Strategy (MicroStrategy)", "stock"),
]

CRYPTO_SYMBOLS = {symbol for _, symbol, _ in CRYPTOS}
STOCK_SYMBOLS = {symbol for _, symbol, _, _ in STOCKS}


class FeedBackend(Protocol):
    async def run(self) -> None:
        """Run the feed until cancelled."""


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def parse_coingecko_markets(payload: list[dict[str, Any]], now: datetime) -> list[AssetQuote]:
    names = {cid: (symbol, name) for cid, symbol, name in CRYPTOS}
    quotes: list[AssetQuote] = []
    for entry in payload:
        mapped = names.get(str(entry.get("id")))
        if mapped is None:
            continue
        symbol, name = mapped
        price = _to_float(entry.get("current_price"))
        if price is None:
            continue
        quotes.append(
            AssetQuote(
                symbol=symbol,
                name=name,
                kind="crypto",
                price=price,
                change_24h_pct=_to_float(entry.get("price_change_percentage_24h")),
                market_cap=_to_float(entry.get("market_cap")),
                volume_24h=_to_float(entry.get("total_volume")),
                observed_at=now,
            )
        )
    return quotes


def parse_coingecko_global(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    """Return (total market cap USD, BTC dominance percent)."""
    data = payload.get("data") or {}
    total = None
    caps = data.get("total_market_cap")
    if isinstance(caps, dict):
        total = _to_float(caps.get("usd"))
    dominance = None
    shares = data.get("market_cap_percentage")
    if isinstance(shares, dict):
        dominance = _to_float(shares.get("btc"))
    return total, dominance


def parse_fear_greed(payload: dict[str, Any]) -> tuple[int | None, str | None]:
    entries = payload.get("data") or []
    if not entries:
        return None, None
    entry = entries[0]
    value = _to_float(entry.get("value"))
    label = entry.get("value_classification")
    return (int(value) if value is not None else None), (str(label) if label else None)


def parse_stooq_csv(text: str, now: datetime) -> list[AssetQuote]:
    """Parse Stooq's snapshot CSV (Symbol,Date,Time,Open,High,Low,Close,Volume)."""
    names = {stooq.upper(): (symbol, name, kind) for stooq, symbol, name, kind in STOCKS}
    quotes: list[AssetQuote] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        mapped = names.get(str(row.get("Symbol", "")).upper())
        if mapped is None:
            continue
        symbol, name, kind = mapped
        close = _to_float(row.get("Close"))
        if close is None:  # Stooq reports "N/D" for unknown symbols
            continue
        open_price = _to_float(row.get("Open"))
        change = None
        if open_price:
            change = (close - open_price) / open_price * 100.0
        quotes.append(
            AssetQuote(
                symbol=symbol,
                name=name,
                kind=kind,
                price=close,
                change_24h_pct=round(change, 3) if change is not None else None,
                volume_24h=_to_float(row.get("Volume")),
                observed_at=now,
            )
        )
    return quotes


@dataclass
class LiveFeedBackend:
    """Polls CoinGecko + Stooq + Fear & Greed on an interval."""

    state: MarketState
    interval: float = 60.0
    request_timeout: float = 30.0

    async def run(self) -> None:
        quotes, global_stats = await self._poll_once(strict=True)
        LOGGER.info("Live market poll returned %d quotes", len(quotes))
        await self.state.ingest_cycle(quotes, global_stats)
        while True:
            await asyncio.sleep(self.interval)
            try:
                quotes, global_stats = await self._poll_once(strict=False)
            except Exception as exc:
                LOGGER.warning("Market poll failed (%s); keeping previous cycle", exc)
                await self.state.add_system_event("poll-error", f"Market poll failed: {exc}")
                continue
            await self.state.ingest_cycle(quotes, global_stats)

    async def _poll_once(self, *, strict: bool) -> tuple[list[AssetQuote], GlobalStats]:
        now = datetime.now(UTC)
        quotes: list[AssetQuote] = []

        ids = ",".join(cid for cid, _, _ in CRYPTOS)
        markets_url = (
            f"{COINGECKO_BASE}/coins/markets?"
            + urllib.parse.urlencode({"vs_currency": "usd", "ids": ids, "per_page": len(CRYPTOS)})
        )
        crypto_payload = await asyncio.to_thread(self._fetch_json, markets_url)
        quotes.extend(parse_coingecko_markets(crypto_payload, now))
        if strict and not quotes:
            raise RuntimeError("CoinGecko returned no crypto quotes")

        total_mcap = dominance = None
        fear_value: int | None = None
        fear_label: str | None = None
        try:
            total_mcap, dominance = parse_coingecko_global(
                await asyncio.to_thread(self._fetch_json, f"{COINGECKO_BASE}/global")
            )
        except Exception as exc:
            LOGGER.warning("CoinGecko /global failed: %s", exc)
        try:
            fear_value, fear_label = parse_fear_greed(
                await asyncio.to_thread(self._fetch_json, FEAR_GREED_URL)
            )
        except Exception as exc:
            LOGGER.warning("Fear & Greed fetch failed: %s", exc)

        try:
            stooq_symbols = ",".join(stooq for stooq, _, _, _ in STOCKS)
            stooq_url = STOOQ_BASE + "?" + urllib.parse.urlencode(
                {"s": stooq_symbols, "f": "sd2t2ohlcv", "h": "", "e": "csv"}
            )
            quotes.extend(parse_stooq_csv(await asyncio.to_thread(self._fetch_text, stooq_url), now))
        except Exception as exc:
            LOGGER.warning("Stooq stock fetch failed: %s", exc)

        return quotes, GlobalStats(
            total_market_cap_usd=total_mcap,
            btc_dominance_pct=dominance,
            fear_greed_value=fear_value,
            fear_greed_label=fear_label,
        )

    def _fetch_text(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "market-radar/0.1"})
        with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
            return response.read().decode("utf-8")

    def _fetch_json(self, url: str) -> Any:
        return json.loads(self._fetch_text(url))


@dataclass
class _SimAsset:
    symbol: str
    name: str
    kind: str
    price: float
    day_anchor: float
    market_cap: float | None
    volume_24h: float | None
    drift: float
    noise: float


# Starting prices roughly shaped like a real board (values are simulated).
_DEMO_CRYPTOS: list[tuple[str, str, float, float]] = [
    # symbol, name, start price, market cap ($B)
    ("BTC", "Bitcoin", 97_400.0, 1_920.0),
    ("ETH", "Ethereum", 3_420.0, 411.0),
    ("SOL", "Solana", 204.0, 96.0),
    ("XRP", "XRP", 2.35, 134.0),
    ("BNB", "BNB", 655.0, 95.0),
    ("ADA", "Cardano", 0.92, 32.0),
    ("DOGE", "Dogecoin", 0.31, 46.0),
    ("AVAX", "Avalanche", 38.0, 16.0),
    ("DOT", "Polkadot", 7.1, 11.0),
    ("LINK", "Chainlink", 21.4, 13.0),
    ("LTC", "Litecoin", 104.0, 7.8),
    ("TRX", "TRON", 0.24, 21.0),
]

_DEMO_STOCKS: list[tuple[str, str, str, float]] = [
    ("SPY", "S&P 500 ETF", "index", 602.0),
    ("QQQ", "Nasdaq 100 ETF", "index", 528.0),
    ("DIA", "Dow Jones ETF", "index", 442.0),
    ("NVDA", "NVIDIA", "stock", 141.0),
    ("AAPL", "Apple", "stock", 236.0),
    ("COIN", "Coinbase", "stock", 302.0),
    ("MSTR", "Strategy (MicroStrategy)", "stock", 396.0),
]


@dataclass
class DemoFeedBackend:
    """Simulated market session: calm drift, risk-off shock, relief rally."""

    state: MarketState
    interval: float = 2.0
    shock_at: int = 12
    rally_at: int = 26
    _assets: list[_SimAsset] = field(init=False, default_factory=list)
    _fear_greed: float = field(init=False, default=61.0)

    def __post_init__(self) -> None:
        random.seed(20260828)
        for symbol, name, price, mcap_billion in _DEMO_CRYPTOS:
            self._assets.append(
                _SimAsset(
                    symbol=symbol,
                    name=name,
                    kind="crypto",
                    price=price,
                    day_anchor=price * random.uniform(0.985, 1.01),
                    market_cap=mcap_billion * 1e9,
                    volume_24h=mcap_billion * 1e9 * random.uniform(0.02, 0.09),
                    drift=random.uniform(-0.0006, 0.0012),
                    noise=random.uniform(0.0015, 0.004),
                )
            )
        for symbol, name, kind, price in _DEMO_STOCKS:
            self._assets.append(
                _SimAsset(
                    symbol=symbol,
                    name=name,
                    kind=kind,
                    price=price,
                    day_anchor=price * random.uniform(0.995, 1.004),
                    market_cap=None,
                    volume_24h=random.uniform(2e6, 6e7),
                    drift=random.uniform(-0.0002, 0.0005),
                    noise=random.uniform(0.0006, 0.0018),
                )
            )

    async def run(self) -> None:
        LOGGER.info(
            "Starting demo market simulator (shock at tick %d, rally at tick %d)",
            self.shock_at,
            self.rally_at,
        )
        tick = 0
        while True:
            tick += 1
            quotes, global_stats = self.generate_cycle(tick)
            await self.state.ingest_cycle(quotes, global_stats)
            await asyncio.sleep(self.interval)

    def generate_cycle(self, tick: int) -> tuple[list[AssetQuote], GlobalStats]:
        now = datetime.now(UTC)
        for asset in self._assets:
            step = asset.drift + random.gauss(0.0, asset.noise)
            if tick == self.shock_at:
                # Risk-off: everything sells, alts hardest, BTC least.
                if asset.symbol == "BTC":
                    step -= 0.035
                elif asset.kind == "crypto":
                    step -= random.uniform(0.07, 0.12)
                elif asset.symbol in {"COIN", "MSTR"}:
                    step -= random.uniform(0.05, 0.08)
                else:
                    step -= random.uniform(0.02, 0.035)
            elif self.shock_at < tick < self.rally_at:
                step -= 0.002  # slow bleed after the shock
            elif tick == self.rally_at:
                step += random.uniform(0.03, 0.06) if asset.kind == "crypto" else random.uniform(0.012, 0.02)
            elif tick > self.rally_at:
                step += 0.0015
            asset.price = max(asset.price * (1.0 + step), 0.0001)

        if tick == self.shock_at:
            self._fear_greed = 24.0
        elif self.shock_at < tick < self.rally_at:
            self._fear_greed = max(self._fear_greed - 0.5, 12.0)
        elif tick >= self.rally_at:
            self._fear_greed = min(self._fear_greed + 2.0, 68.0)

        quotes: list[AssetQuote] = []
        for asset in self._assets:
            change = (asset.price / asset.day_anchor - 1.0) * 100.0
            market_cap = asset.market_cap
            if market_cap is not None:
                market_cap = market_cap * (1.0 + change / 100.0)
            quotes.append(
                AssetQuote(
                    symbol=asset.symbol,
                    name=asset.name,
                    kind=asset.kind,
                    price=asset.price,
                    change_24h_pct=round(change, 3),
                    market_cap=market_cap,
                    volume_24h=asset.volume_24h,
                    observed_at=now,
                )
            )

        crypto_caps = [q.market_cap for q in quotes if q.kind == "crypto" and q.market_cap]
        total = sum(crypto_caps) if crypto_caps else None
        btc_cap = next((q.market_cap for q in quotes if q.symbol == "BTC"), None)
        dominance = (btc_cap / total * 100.0) if btc_cap and total else None
        value = int(round(self._fear_greed))
        return quotes, GlobalStats(
            total_market_cap_usd=total,
            btc_dominance_pct=round(dominance, 2) if dominance is not None else None,
            fear_greed_value=value,
            fear_greed_label=fear_greed_label(value),
        )


def fear_greed_label(value: int) -> str:
    if value <= 24:
        return "Extreme Fear"
    if value <= 44:
        return "Fear"
    if value <= 55:
        return "Neutral"
    if value <= 74:
        return "Greed"
    return "Extreme Greed"
