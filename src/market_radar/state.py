"""In-memory market state: quotes, price history, health score, and alarms."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Health-score component weights (renormalized when a component is missing).
HEALTH_WEIGHTS = {"breadth": 0.30, "crypto": 0.30, "stocks": 0.20, "sentiment": 0.20}
RISK_OFF_THRESHOLD = 30.0
RISK_OFF_CLEAR = 42.0
CRYPTO_MOVER_PCT = 5.0
STOCK_MOVER_PCT = 2.0


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass
class AssetQuote:
    symbol: str
    name: str
    kind: str  # "crypto" | "index" | "stock"
    price: float
    change_24h_pct: float | None = None
    market_cap: float | None = None
    volume_24h: float | None = None
    observed_at: datetime = field(default_factory=utc_now)


@dataclass
class GlobalStats:
    total_market_cap_usd: float | None = None
    btc_dominance_pct: float | None = None
    fear_greed_value: int | None = None
    fear_greed_label: str | None = None


@dataclass
class AssetTrack:
    quote: AssetQuote
    first_seen: datetime
    session_high: float
    session_low: float
    price_history: deque[float] = field(default_factory=lambda: deque(maxlen=180))
    time_history: deque[str] = field(default_factory=lambda: deque(maxlen=180))

    def update(self, quote: AssetQuote) -> None:
        self.quote = quote
        self.session_high = max(self.session_high, quote.price)
        self.session_low = min(self.session_low, quote.price)
        self.price_history.append(quote.price)
        self.time_history.append(iso_time(quote.observed_at))

    def snapshot(self) -> dict[str, Any]:
        quote = self.quote
        return {
            "symbol": quote.symbol,
            "name": quote.name,
            "kind": quote.kind,
            "price": quote.price,
            "change_24h_pct": quote.change_24h_pct,
            "market_cap": quote.market_cap,
            "volume_24h": quote.volume_24h,
            "session_high": self.session_high,
            "session_low": self.session_low,
            "price_history": list(self.price_history),
            "time_history": list(self.time_history),
            "last_seen": iso_time(quote.observed_at),
        }


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def compute_health(quotes: list[AssetQuote], global_stats: GlobalStats | None) -> dict[str, Any]:
    """Composite 0-100 market health from breadth, momentum, and sentiment."""
    changes = [q.change_24h_pct for q in quotes if q.change_24h_pct is not None]
    crypto_changes = [
        q.change_24h_pct for q in quotes if q.kind == "crypto" and q.change_24h_pct is not None
    ]
    stock_changes = [
        q.change_24h_pct for q in quotes if q.kind != "crypto" and q.change_24h_pct is not None
    ]

    components: dict[str, float | None] = {
        "breadth": (sum(1 for c in changes if c >= 0) / len(changes) * 100.0) if changes else None,
        "crypto": clamp(50.0 + sum(crypto_changes) / len(crypto_changes) * 6.0) if crypto_changes else None,
        "stocks": clamp(50.0 + sum(stock_changes) / len(stock_changes) * 12.0) if stock_changes else None,
        "sentiment": float(global_stats.fear_greed_value)
        if global_stats and global_stats.fear_greed_value is not None
        else None,
    }

    weighted = [(HEALTH_WEIGHTS[key], value) for key, value in components.items() if value is not None]
    total_weight = sum(weight for weight, _ in weighted)
    score = sum(weight * value for weight, value in weighted) / total_weight if total_weight else None

    return {
        "score": round(score, 1) if score is not None else None,
        "label": health_label(score),
        "components": {
            key: (round(value, 1) if value is not None else None) for key, value in components.items()
        },
    }


def health_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score < 25:
        return "severe risk-off"
    if score < 40:
        return "risk-off"
    if score < 60:
        return "mixed"
    if score < 80:
        return "healthy"
    return "euphoric"


class MarketState:
    """Tracks assets across poll cycles and raises the risk-off alarm."""

    def __init__(self, *, data_source: str = "live") -> None:
        self.data_source = data_source
        self._assets: dict[str, AssetTrack] = {}
        self._global: GlobalStats = GlobalStats()
        self._health: dict[str, Any] = {"score": None, "label": "unknown", "components": {}}
        self._events: deque[dict[str, Any]] = deque(maxlen=300)
        self._history: deque[dict[str, Any]] = deque(maxlen=360)
        self._alarm_active = False
        self._mover_flags: dict[str, str] = {}
        self._cycles = 0
        self._lock = asyncio.Lock()

    async def ingest_cycle(
        self, quotes: list[AssetQuote], global_stats: GlobalStats | None = None
    ) -> list[dict[str, Any]]:
        async with self._lock:
            now = utc_now()
            self._cycles += 1
            emitted: list[dict[str, Any]] = []

            for quote in quotes:
                track = self._assets.get(quote.symbol)
                if track is None:
                    track = AssetTrack(
                        quote=quote,
                        first_seen=quote.observed_at,
                        session_high=quote.price,
                        session_low=quote.price,
                    )
                    self._assets[quote.symbol] = track
                track.update(quote)
                emitted.extend(self._detect_mover(quote, now))

            if global_stats is not None:
                self._global = global_stats

            latest = [track.quote for track in self._assets.values()]
            self._health = compute_health(latest, self._global)
            score = self._health["score"]

            if score is not None:
                if not self._alarm_active and score < RISK_OFF_THRESHOLD:
                    self._alarm_active = True
                    emitted.append(
                        self._system_event(
                            "risk-off-alarm",
                            f"RISK-OFF: market health fell to {score:.0f}/100 "
                            f"({self._health['label']}).",
                            alarm=True,
                            at=now,
                        )
                    )
                elif self._alarm_active and score >= RISK_OFF_CLEAR:
                    self._alarm_active = False
                    emitted.append(
                        self._system_event(
                            "alarm-cleared",
                            f"Market health recovered to {score:.0f}/100; risk-off alarm cleared.",
                            at=now,
                        )
                    )

            btc = self._assets.get("BTC")
            self._history.append(
                {
                    "at": iso_time(now),
                    "health": score,
                    "btc_price": btc.quote.price if btc else None,
                    "fear_greed": self._global.fear_greed_value,
                    "alarm": self._alarm_active,
                }
            )
            self._events.extend(emitted)
            return emitted

    def _detect_mover(self, quote: AssetQuote, now: datetime) -> list[dict[str, Any]]:
        change = quote.change_24h_pct
        if change is None:
            return []
        threshold = CRYPTO_MOVER_PCT if quote.kind == "crypto" else STOCK_MOVER_PCT
        direction = "up" if change >= threshold else "down" if change <= -threshold else ""
        previous = self._mover_flags.get(quote.symbol, "")
        if direction == previous:
            return []
        self._mover_flags[quote.symbol] = direction
        if not direction:
            return []
        arrow = "surged" if direction == "up" else "dropped"
        window = "24h" if quote.kind == "crypto" else "session"
        return [
            {
                "type": f"mover-{direction}",
                "symbol": quote.symbol,
                "identity": quote.name,
                "message": f"{quote.name} ({quote.symbol}) {arrow} {change:+.1f}% ({window})",
                "alarm": False,
                "at": iso_time(now),
            }
        ]

    async def add_system_event(self, event_type: str, message: str) -> dict[str, Any]:
        async with self._lock:
            event = self._system_event(event_type, message)
            self._events.append(event)
            return event

    async def set_data_source(self, source: str) -> None:
        async with self._lock:
            self.data_source = source

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            now = utc_now()
            cryptos = [
                t.snapshot() for t in self._assets.values() if t.quote.kind == "crypto"
            ]
            cryptos.sort(key=lambda item: item["market_cap"] or 0.0, reverse=True)
            stocks = [t.snapshot() for t in self._assets.values() if t.quote.kind != "crypto"]
            stocks.sort(key=lambda item: (item["kind"] != "index", item["symbol"]))
            movers = sorted(
                (a for a in cryptos + stocks if a["change_24h_pct"] is not None),
                key=lambda item: abs(item["change_24h_pct"]),
                reverse=True,
            )[:5]
            return {
                "generated_at": iso_time(now),
                "data_source": self.data_source,
                "cycles": self._cycles,
                "alarm_active": self._alarm_active,
                "health": self._health,
                "global": {
                    "total_market_cap_usd": self._global.total_market_cap_usd,
                    "btc_dominance_pct": self._global.btc_dominance_pct,
                    "fear_greed_value": self._global.fear_greed_value,
                    "fear_greed_label": self._global.fear_greed_label,
                },
                "top_movers": [
                    {
                        "symbol": m["symbol"],
                        "name": m["name"],
                        "kind": m["kind"],
                        "change_24h_pct": m["change_24h_pct"],
                    }
                    for m in movers
                ],
                "cryptos": cryptos,
                "stocks": stocks,
                "history": list(self._history),
                "events": list(self._events),
            }

    def _system_event(
        self, event_type: str, message: str, *, alarm: bool = False, at: datetime | None = None
    ) -> dict[str, Any]:
        return {
            "type": event_type,
            "symbol": "system",
            "identity": "Market Radar",
            "message": message,
            "alarm": alarm,
            "at": iso_time(at or utc_now()),
        }
