"""Live and demo market-data backends."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from .universe import CRYPTO, EQUITIES, CryptoSpec, EquitySpec

LOGGER = logging.getLogger(__name__)

COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "btc-radar/0.1 (local dashboard; +https://github.com/zeekgeek/zeekgeek)"


@dataclass
class Quote:
    symbol: str
    name: str
    kind: str
    price: float | None
    change_1h: float | None = None
    change_24h: float | None = None
    change_7d: float | None = None
    volume: float | None = None
    market_cap: float | None = None
    rank: int | None = None
    sparkline: list[float] = field(default_factory=list)
    is_stable: bool = False
    coin_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "kind": self.kind,
            "price": self.price,
            "change_1h": self.change_1h,
            "change_24h": self.change_24h,
            "change_7d": self.change_7d,
            "volume": self.volume,
            "market_cap": self.market_cap,
            "rank": self.rank,
            "sparkline": self.sparkline[-96:],
            "is_stable": self.is_stable,
            "coin_id": self.coin_id,
        }


@dataclass
class MarketSnapshot:
    cryptos: list[Quote]
    equities: list[Quote]
    fear_greed: float | None
    fear_greed_label: str | None
    total_market_cap: float | None
    total_volume: float | None
    btc_dominance: float | None
    eth_dominance: float | None
    market_cap_change_24h: float | None
    source: str
    fetched_at: datetime

    def btc(self) -> Quote | None:
        for quote in self.cryptos:
            if quote.symbol == "BTC":
                return quote
        return None

    def equity(self, symbol: str) -> Quote | None:
        needle = symbol.upper()
        for quote in self.equities:
            if quote.symbol.upper() == needle:
                return quote
        return None


class FeedBackend(Protocol):
    async def fetch(self) -> MarketSnapshot:
        """Return one complete market snapshot."""


def fetch_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) and not isinstance(payload, list):
        raise ValueError(f"Unexpected JSON type from {url}")
    if isinstance(payload, list):
        return {"items": payload}
    return payload


def parse_coingecko_markets(items: list[dict[str, Any]]) -> list[Quote]:
    by_id = {spec.coin_id: spec for spec in CRYPTO}
    quotes: list[Quote] = []
    for item in items:
        spec = by_id.get(str(item.get("id") or ""))
        if spec is None:
            continue
        spark = item.get("sparkline_in_7d") or {}
        prices = [float(value) for value in (spark.get("price") or []) if value is not None]
        quotes.append(
            Quote(
                symbol=spec.symbol,
                name=spec.name,
                kind="crypto",
                price=_num(item.get("current_price")),
                change_1h=_num(item.get("price_change_percentage_1h_in_currency")),
                change_24h=_num(
                    item.get("price_change_percentage_24h_in_currency")
                    if item.get("price_change_percentage_24h_in_currency") is not None
                    else item.get("price_change_percentage_24h")
                ),
                change_7d=_num(item.get("price_change_percentage_7d_in_currency")),
                volume=_num(item.get("total_volume")),
                market_cap=_num(item.get("market_cap")),
                rank=int(item["market_cap_rank"]) if item.get("market_cap_rank") is not None else None,
                sparkline=prices,
                is_stable=spec.is_stable,
                coin_id=spec.coin_id,
            )
        )
    order = {spec.coin_id: index for index, spec in enumerate(CRYPTO)}
    quotes.sort(key=lambda quote: order.get(quote.coin_id or "", 999))
    return quotes


def parse_coingecko_global(payload: dict[str, Any]) -> dict[str, float | None]:
    data = payload.get("data") or payload
    caps = data.get("total_market_cap") or {}
    volumes = data.get("total_volume") or {}
    dominance = data.get("market_cap_percentage") or {}
    return {
        "total_market_cap": _num(caps.get("usd")),
        "total_volume": _num(volumes.get("usd")),
        "btc_dominance": _num(dominance.get("btc")),
        "eth_dominance": _num(dominance.get("eth")),
        "market_cap_change_24h": _num(data.get("market_cap_change_percentage_24h_usd")),
    }


def parse_fear_greed(payload: dict[str, Any]) -> tuple[float | None, str | None]:
    rows = payload.get("data") or []
    if not rows:
        return None, None
    row = rows[0]
    return _num(row.get("value")), str(row.get("value_classification") or "") or None


def parse_yahoo_chart(payload: dict[str, Any], spec: EquitySpec) -> Quote:
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    meta = result.get("meta") or {}
    price = _num(meta.get("regularMarketPrice") or meta.get("previousClose"))
    previous = _num(meta.get("chartPreviousClose") or meta.get("previousClose"))
    change = None
    if price is not None and previous not in (None, 0):
        change = 100.0 * (price / previous - 1.0)
    closes: list[float] = []
    quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    for value in quotes.get("close") or []:
        if value is not None:
            closes.append(float(value))
    return Quote(
        symbol=spec.symbol,
        name=spec.name,
        kind=spec.kind,
        price=price,
        change_24h=change,
        sparkline=closes,
    )


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class LiveFeed:
    timeout: float = 20.0

    async def fetch(self) -> MarketSnapshot:
        markets_url = (
            COINGECKO_MARKETS
            + "?"
            + urllib.parse.urlencode(
                {
                    "vs_currency": "usd",
                    "ids": ",".join(spec.coin_id for spec in CRYPTO),
                    "order": "market_cap_desc",
                    "per_page": str(len(CRYPTO)),
                    "page": "1",
                    "sparkline": "true",
                    "price_change_percentage": "1h,24h,7d",
                }
            )
        )
        crypto_task = asyncio.to_thread(self._get, markets_url)
        global_task = asyncio.to_thread(self._get, COINGECKO_GLOBAL)
        fng_task = asyncio.to_thread(self._get, FEAR_GREED_URL)
        equity_tasks = [
            asyncio.to_thread(self._yahoo, spec) for spec in EQUITIES
        ]
        crypto_raw, global_raw, fng_raw, *equity_results = await asyncio.gather(
            crypto_task, global_task, fng_task, *equity_tasks, return_exceptions=True
        )

        if isinstance(crypto_raw, Exception):
            raise crypto_raw
        items = crypto_raw.get("items") if "items" in crypto_raw else crypto_raw
        if isinstance(items, dict):
            items = items.get("items") or []
        cryptos = parse_coingecko_markets(list(items))
        if not cryptos:
            raise RuntimeError("CoinGecko returned no matching coins")

        globals_parsed = {
            "total_market_cap": None,
            "total_volume": None,
            "btc_dominance": None,
            "eth_dominance": None,
            "market_cap_change_24h": None,
        }
        if not isinstance(global_raw, Exception):
            globals_parsed = parse_coingecko_global(global_raw)
        else:
            LOGGER.warning("CoinGecko global failed: %s", global_raw)

        fear_greed, fear_label = None, None
        if not isinstance(fng_raw, Exception):
            fear_greed, fear_label = parse_fear_greed(fng_raw)
        else:
            LOGGER.warning("Fear & Greed failed: %s", fng_raw)

        equities: list[Quote] = []
        for spec, result in zip(EQUITIES, equity_results, strict=True):
            if isinstance(result, Exception):
                LOGGER.warning("Yahoo %s failed: %s", spec.symbol, result)
                equities.append(Quote(symbol=spec.symbol, name=spec.name, kind=spec.kind, price=None))
                continue
            equities.append(result)

        source = "live"
        if all(quote.price is None for quote in equities):
            source = "crypto-only"

        return MarketSnapshot(
            cryptos=cryptos,
            equities=equities,
            fear_greed=fear_greed,
            fear_greed_label=fear_label,
            total_market_cap=globals_parsed["total_market_cap"],
            total_volume=globals_parsed["total_volume"],
            btc_dominance=globals_parsed["btc_dominance"],
            eth_dominance=globals_parsed["eth_dominance"],
            market_cap_change_24h=globals_parsed["market_cap_change_24h"],
            source=source,
            fetched_at=datetime.now(UTC),
        )

    def _get(self, url: str) -> dict[str, Any]:
        try:
            return fetch_json(url, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} for {url}") from exc

    def _yahoo(self, spec: EquitySpec) -> Quote:
        encoded = urllib.parse.quote(spec.yahoo, safe="")
        url = YAHOO_CHART.format(symbol=encoded) + "?range=5d&interval=1d&includePrePost=false"
        payload = self._get(url)
        return parse_yahoo_chart(payload, spec)


@dataclass
class DemoFeed:
    """Offline correlated market that cycles calm → risk-on → risk-off."""

    tick: int = 0
    rng: random.Random = field(default_factory=lambda: random.Random(42))
    _crypto_state: dict[str, dict[str, float]] = field(default_factory=dict)
    _equity_state: dict[str, dict[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self._crypto_state:
            self._crypto_state = {spec.coin_id: dict(DEMO_CRYPTO[spec.coin_id]) for spec in CRYPTO}
        if not self._equity_state:
            self._equity_state = {spec.symbol: dict(DEMO_EQUITY[spec.symbol]) for spec in EQUITIES}

    async def fetch(self) -> MarketSnapshot:
        self.tick += 1
        phase = self._phase()
        risk = phase["risk"]
        for spec in CRYPTO:
            state = self._crypto_state[spec.coin_id]
            if spec.is_stable:
                state["price"] = 1.0 + self.rng.uniform(-0.0004, 0.0004)
                state["change_24h"] = (state["price"] - 1.0) * 100
                state["change_1h"] = self.rng.uniform(-0.02, 0.02)
                state["change_7d"] = self.rng.uniform(-0.05, 0.05)
            else:
                beta = 1.0 if spec.is_btc else 1.35 + (hash(spec.symbol) % 40) / 100.0
                shock = risk * 0.12 * beta + self.rng.uniform(-0.004, 0.004)
                state["price"] *= 1.0 + shock
                state["change_1h"] = shock * 100 + self.rng.uniform(-0.15, 0.15)
                state["change_24h"] = risk * 6.5 * beta + self.rng.uniform(-0.4, 0.4)
                state["change_7d"] = risk * 11 * beta + self.rng.uniform(-1.2, 1.2)
                spark = state.setdefault("spark", [state["price"]] * 48)
                spark.append(state["price"])
                del spark[:-96]

        for spec in EQUITIES:
            state = self._equity_state[spec.symbol]
            if spec.symbol == "VIX":
                state["price"] = clamp_price(14.5 - risk * 9 + self.rng.uniform(-0.4, 0.4), 11.0, 42.0)
                state["change_24h"] = -risk * 8 + self.rng.uniform(-0.5, 0.5)
            elif spec.symbol == "TNX":
                state["price"] = clamp_price(4.15 - risk * 0.18 + self.rng.uniform(-0.02, 0.02), 3.2, 5.4)
                state["change_24h"] = -risk * 1.4 + self.rng.uniform(-0.1, 0.1)
            elif spec.symbol == "UUP":
                state["price"] *= 1.0 - risk * 0.004 + self.rng.uniform(-0.0008, 0.0008)
                state["change_24h"] = -risk * 0.55 + self.rng.uniform(-0.08, 0.08)
            elif spec.symbol in {"GLD", "SLV"}:
                state["price"] *= 1.0 + (-risk * 0.003) + self.rng.uniform(-0.001, 0.001)
                state["change_24h"] = -risk * 0.7 + self.rng.uniform(-0.15, 0.15)
            else:
                beta = 1.25 if spec.kind == "mega" else 0.85
                if spec.symbol == "IWM":
                    beta = 1.1
                if spec.symbol == "QQQ":
                    beta = 1.05
                state["price"] *= 1.0 + risk * 0.012 * beta + self.rng.uniform(-0.0015, 0.0015)
                state["change_24h"] = risk * 1.8 * beta + self.rng.uniform(-0.15, 0.15)
            spark = state.setdefault("spark", [state["price"]] * 8)
            spark.append(state["price"])
            del spark[:-48]

        cryptos = [self._crypto_quote(spec) for spec in CRYPTO]
        equities = [self._equity_quote(spec) for spec in EQUITIES]
        btc = self._crypto_state["bitcoin"]
        fng = clamp_price(50 + risk * 32 + self.rng.uniform(-3, 3), 5, 95)
        dominance = clamp_price(53.5 - risk * 3.5, 48.0, 62.0)
        total_cap = sum(q.market_cap or 0 for q in cryptos) * 1.35
        return MarketSnapshot(
            cryptos=cryptos,
            equities=equities,
            fear_greed=fng,
            fear_greed_label=_fng_label(fng),
            total_market_cap=total_cap,
            total_volume=total_cap * 0.045,
            btc_dominance=dominance,
            eth_dominance=14.2 + risk * 0.8,
            market_cap_change_24h=btc["change_24h"] * 0.85,
            source="demo",
            fetched_at=datetime.now(UTC),
        )

    def _phase(self) -> dict[str, float]:
        # Slow sine + two scripted episodes so the demo is not just noise.
        wave = math.sin(self.tick / 18.0)
        if 40 <= self.tick % 90 <= 55:
            return {"risk": 0.85, "name": "risk-on"}
        if 70 <= self.tick % 90 <= 82:
            return {"risk": -0.95, "name": "risk-off"}
        return {"risk": 0.15 * wave, "name": "mixed"}

    def _crypto_quote(self, spec: CryptoSpec) -> Quote:
        state = self._crypto_state[spec.coin_id]
        return Quote(
            symbol=spec.symbol,
            name=spec.name,
            kind="crypto",
            price=state["price"],
            change_1h=state.get("change_1h"),
            change_24h=state.get("change_24h"),
            change_7d=state.get("change_7d"),
            volume=state["price"] * state.get("unit_volume", 1_000_000),
            market_cap=state["price"] * state.get("supply", 1_000_000),
            sparkline=list(state.get("spark") or [state["price"]]),
            is_stable=spec.is_stable,
            coin_id=spec.coin_id,
        )

    def _equity_quote(self, spec: EquitySpec) -> Quote:
        state = self._equity_state[spec.symbol]
        return Quote(
            symbol=spec.symbol,
            name=spec.name,
            kind=spec.kind,
            price=state["price"],
            change_24h=state.get("change_24h"),
            sparkline=list(state.get("spark") or [state["price"]]),
        )


def clamp_price(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _fng_label(value: float) -> str:
    if value <= 20:
        return "Extreme Fear"
    if value <= 40:
        return "Fear"
    if value <= 60:
        return "Neutral"
    if value <= 80:
        return "Greed"
    return "Extreme Greed"


DEMO_CRYPTO: dict[str, dict[str, float]] = {
    "bitcoin": {"price": 108_450.0, "supply": 19_780_000, "unit_volume": 280_000},
    "ethereum": {"price": 4_120.0, "supply": 120_400_000, "unit_volume": 4_200_000},
    "solana": {"price": 178.0, "supply": 470_000_000, "unit_volume": 18_000_000},
    "ripple": {"price": 2.42, "supply": 56_000_000_000, "unit_volume": 1_100_000_000},
    "binancecoin": {"price": 645.0, "supply": 145_000_000, "unit_volume": 4_800_000},
    "dogecoin": {"price": 0.168, "supply": 146_000_000_000, "unit_volume": 4_200_000_000},
    "cardano": {"price": 0.72, "supply": 35_000_000_000, "unit_volume": 890_000_000},
    "avalanche-2": {"price": 36.4, "supply": 420_000_000, "unit_volume": 22_000_000},
    "chainlink": {"price": 18.9, "supply": 678_000_000, "unit_volume": 28_000_000},
    "polkadot": {"price": 6.85, "supply": 1_520_000_000, "unit_volume": 55_000_000},
    "the-open-network": {"price": 5.42, "supply": 2_500_000_000, "unit_volume": 90_000_000},
    "tron": {"price": 0.27, "supply": 86_000_000_000, "unit_volume": 2_400_000_000},
    "sui": {"price": 2.85, "supply": 2_900_000_000, "unit_volume": 180_000_000},
    "litecoin": {"price": 92.0, "supply": 75_000_000, "unit_volume": 4_200_000},
    "near": {"price": 5.15, "supply": 1_200_000_000, "unit_volume": 48_000_000},
    "uniswap": {"price": 9.4, "supply": 600_000_000, "unit_volume": 22_000_000},
    "shiba-inu": {"price": 0.0000185, "supply": 589_000_000_000_000, "unit_volume": 18_000_000_000_000},
    "pepe": {"price": 0.0000098, "supply": 420_690_000_000_000, "unit_volume": 12_000_000_000_000},
    "tether": {"price": 1.0, "supply": 120_000_000_000, "unit_volume": 80_000_000_000},
    "usd-coin": {"price": 1.0, "supply": 42_000_000_000, "unit_volume": 8_000_000_000},
}

DEMO_EQUITY: dict[str, dict[str, float]] = {
    "SPY": {"price": 562.4},
    "QQQ": {"price": 492.1},
    "DIA": {"price": 412.8},
    "IWM": {"price": 218.6},
    "NVDA": {"price": 128.4},
    "AAPL": {"price": 228.9},
    "MSFT": {"price": 428.2},
    "GOOGL": {"price": 178.5},
    "AMZN": {"price": 198.3},
    "META": {"price": 542.0},
    "TSLA": {"price": 248.7},
    "GLD": {"price": 232.1},
    "SLV": {"price": 27.4},
    "USO": {"price": 78.6},
    "UUP": {"price": 28.9},
    "VIX": {"price": 16.2},
    "TNX": {"price": 4.18},
}
