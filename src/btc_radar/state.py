"""In-memory quotes, health, and event log for the Bitcoin radar."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime
from typing import Any

from .feed import MarketSnapshot, Quote
from .health import HealthInputs, crypto_breadth, detect_events, halving_countdown, score_market
from .universe import ROADMAP


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


class MarketState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.mode = "starting"
        self.source = "starting"
        self.updated_at: datetime | None = None
        self.cryptos: list[Quote] = []
        self.equities: list[Quote] = []
        self.fear_greed: float | None = None
        self.fear_greed_label: str | None = None
        self.total_market_cap: float | None = None
        self.total_volume: float | None = None
        self.btc_dominance: float | None = None
        self.eth_dominance: float | None = None
        self.market_cap_change_24h: float | None = None
        self.health: dict[str, Any] = score_market(HealthInputs(None, None, None, None, None))
        self.events: deque[dict[str, Any]] = deque(maxlen=80)
        self.btc_history: deque[dict[str, Any]] = deque(maxlen=240)
        self._previous_regime: str | None = None
        self._seen_event_keys: deque[str] = deque(maxlen=40)

    async def ingest(self, snapshot: MarketSnapshot, *, mode: str) -> None:
        async with self._lock:
            self.mode = mode
            self.source = snapshot.source
            self.updated_at = snapshot.fetched_at
            self.cryptos = snapshot.cryptos
            self.equities = snapshot.equities
            self.fear_greed = snapshot.fear_greed
            self.fear_greed_label = snapshot.fear_greed_label
            self.total_market_cap = snapshot.total_market_cap
            self.total_volume = snapshot.total_volume
            self.btc_dominance = snapshot.btc_dominance
            self.eth_dominance = snapshot.eth_dominance
            self.market_cap_change_24h = snapshot.market_cap_change_24h

            btc = snapshot.btc()
            spy = snapshot.equity("SPY")
            vix = snapshot.equity("VIX")
            alts = [quote for quote in snapshot.cryptos if quote.symbol != "BTC" and not quote.is_stable]
            breadth = crypto_breadth(
                [quote.change_24h for quote in snapshot.cryptos if not quote.is_stable]
            )
            health = score_market(
                HealthInputs(
                    fear_greed=snapshot.fear_greed,
                    breadth_pct_green=breadth["pct_green"],
                    btc_change_24h=None if btc is None else btc.change_24h,
                    spy_change_24h=None if spy is None else spy.change_24h,
                    vix=None if vix is None else vix.price,
                    btc_change_7d=None if btc is None else btc.change_7d,
                    alt_changes_7d=tuple(quote.change_7d for quote in alts),
                    btc_dominance=snapshot.btc_dominance,
                )
            )
            health["breadth"] = {
                "green": breadth["green"],
                "red": breadth["red"],
                "flat": breadth["flat"],
                "pct_green": None if breadth["pct_green"] is None else round(breadth["pct_green"], 1),
                "n": breadth["n"],
            }
            self.health = health

            if btc is not None and btc.price is not None:
                self.btc_history.append(
                    {
                        "t": iso_time(snapshot.fetched_at),
                        "price": btc.price,
                        "change_24h": btc.change_24h,
                    }
                )

            movers = self._hot_movers(snapshot)
            fresh = detect_events(
                previous_regime=self._previous_regime,
                health=health,
                btc_change_24h=None if btc is None else btc.change_24h,
                vix=None if vix is None else vix.price,
                fear_greed=snapshot.fear_greed,
                movers=movers,
            )
            for event in fresh:
                key = f"{event['kind']}:{event['title']}"
                if key in self._seen_event_keys:
                    continue
                self._seen_event_keys.append(key)
                self.events.appendleft(
                    {
                        **event,
                        "ts": iso_time(snapshot.fetched_at),
                    }
                )
            self._previous_regime = str(health.get("regime") or "unknown")

    async def add_system_event(self, kind: str, detail: str) -> None:
        async with self._lock:
            self.events.appendleft(
                {
                    "kind": kind,
                    "title": kind.replace("-", " ").title(),
                    "detail": detail,
                    "ts": iso_time(utc_now()),
                }
            )

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            btc = next((quote for quote in self.cryptos if quote.symbol == "BTC"), None)
            stables = [quote for quote in self.cryptos if quote.is_stable]
            risk_cryptos = [quote for quote in self.cryptos if not quote.is_stable]
            return {
                "mode": self.mode,
                "source": self.source,
                "updated_at": None if self.updated_at is None else iso_time(self.updated_at),
                "bitcoin": None if btc is None else btc.as_dict(),
                "cryptos": [quote.as_dict() for quote in risk_cryptos],
                "stables": [quote.as_dict() for quote in stables],
                "equities": {
                    "indices": [quote.as_dict() for quote in self.equities if quote.kind == "index"],
                    "mega": [quote.as_dict() for quote in self.equities if quote.kind == "mega"],
                    "macro": [quote.as_dict() for quote in self.equities if quote.kind == "macro"],
                },
                "global": {
                    "total_market_cap": self.total_market_cap,
                    "total_volume": self.total_volume,
                    "btc_dominance": self.btc_dominance,
                    "eth_dominance": self.eth_dominance,
                    "market_cap_change_24h": self.market_cap_change_24h,
                    "stablecoin_cap": sum(quote.market_cap or 0 for quote in stables) or None,
                },
                "fear_greed": {
                    "value": self.fear_greed,
                    "label": self.fear_greed_label,
                    "band": self.health.get("fear_greed_band"),
                },
                "health": self.health,
                "halving": halving_countdown(utc_now()),
                "btc_history": list(self.btc_history),
                "events": list(self.events)[:40],
                "roadmap": list(ROADMAP),
                "gainers": self._ranked(risk_cryptos, reverse=True)[:5],
                "losers": self._ranked(risk_cryptos, reverse=False)[:5],
            }

    def _hot_movers(self, snapshot: MarketSnapshot) -> list[tuple[str, float]]:
        movers: list[tuple[str, float]] = []
        for quote in snapshot.cryptos:
            if quote.is_stable or quote.change_24h is None or quote.symbol == "BTC":
                continue
            if abs(quote.change_24h) >= 8:
                movers.append((quote.symbol, quote.change_24h))
        for quote in snapshot.equities:
            if quote.kind != "mega" or quote.change_24h is None:
                continue
            if abs(quote.change_24h) >= 3.5:
                movers.append((quote.symbol, quote.change_24h))
        movers.sort(key=lambda item: abs(item[1]), reverse=True)
        return movers[:4]

    @staticmethod
    def _ranked(quotes: list[Quote], *, reverse: bool) -> list[dict[str, Any]]:
        scored = [quote for quote in quotes if quote.change_24h is not None]
        scored.sort(key=lambda quote: quote.change_24h or 0.0, reverse=reverse)
        return [quote.as_dict() for quote in scored]
