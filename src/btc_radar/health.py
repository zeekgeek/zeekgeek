"""Composite market-health scoring for crypto + equities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .universe import NEXT_HALVING


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def scale(value: float | None, lo: float, hi: float) -> float | None:
    """Map ``value`` in ``[lo, hi]`` onto ``[0, 100]``."""
    if value is None:
        return None
    if hi == lo:
        return 50.0
    return clamp(100.0 * (value - lo) / (hi - lo), 0.0, 100.0)


def invert(score: float | None) -> float | None:
    if score is None:
        return None
    return 100.0 - score


def mean(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def regime_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 62:
        return "risk-on"
    if score <= 38:
        return "risk-off"
    return "mixed"


def crypto_breadth(changes_24h: list[float | None], *, flat_eps: float = 0.15) -> dict[str, Any]:
    known = [change for change in changes_24h if change is not None]
    if not known:
        return {"green": 0, "red": 0, "flat": 0, "pct_green": None, "n": 0}
    green = sum(1 for change in known if change > flat_eps)
    red = sum(1 for change in known if change < -flat_eps)
    flat = len(known) - green - red
    return {
        "green": green,
        "red": red,
        "flat": flat,
        "pct_green": 100.0 * green / len(known),
        "n": len(known),
    }


def altseason_lean(btc_7d: float | None, alt_7d: list[float | None]) -> dict[str, Any]:
    alts = [change for change in alt_7d if change is not None]
    if btc_7d is None or not alts:
        return {"lean": None, "alts_beating_btc": None, "avg_alt_7d": None, "label": "unknown"}
    average = sum(alts) / len(alts)
    beating = sum(1 for change in alts if change > btc_7d)
    beating_pct = 100.0 * beating / len(alts)
    lean = average - btc_7d
    if lean >= 4 and beating_pct >= 60:
        label = "altseason"
    elif lean <= -4:
        label = "btc-season"
    else:
        label = "balanced"
    return {
        "lean": lean,
        "alts_beating_btc": beating_pct,
        "avg_alt_7d": average,
        "label": label,
    }


def same_day_divergence(
    btc_24h: float | None, spy_24h: float | None, *, min_abs: float = 0.4
) -> str | None:
    if btc_24h is None or spy_24h is None:
        return None
    if abs(btc_24h) < min_abs or abs(spy_24h) < min_abs:
        return None
    if btc_24h > 0 and spy_24h < 0:
        return "crypto-led"
    if btc_24h < 0 and spy_24h > 0:
        return "equities-led"
    if btc_24h > 0 and spy_24h > 0:
        return "risk-on-together"
    return "risk-off-together"


def halving_countdown(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    remaining = NEXT_HALVING - current
    days = remaining.days
    hours = remaining.seconds // 3600
    return {
        "target": NEXT_HALVING.date().isoformat(),
        "days": days,
        "hours": hours,
        "label": f"{days}d {hours}h" if days >= 0 else "halving window",
        "past": days < 0,
    }


def fear_greed_band(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 20:
        return "extreme-fear"
    if value <= 40:
        return "fear"
    if value <= 60:
        return "neutral"
    if value <= 80:
        return "greed"
    return "extreme-greed"


@dataclass(frozen=True)
class HealthInputs:
    fear_greed: float | None
    breadth_pct_green: float | None
    btc_change_24h: float | None
    spy_change_24h: float | None
    vix: float | None
    btc_change_7d: float | None = None
    alt_changes_7d: tuple[float | None, ...] = ()
    btc_dominance: float | None = None


def score_market(inputs: HealthInputs) -> dict[str, Any]:
    components = {
        "fear_greed": inputs.fear_greed,
        "breadth": inputs.breadth_pct_green,
        "btc_24h": scale(inputs.btc_change_24h, -8.0, 8.0),
        "spy_24h": scale(inputs.spy_change_24h, -2.5, 2.5),
        "vix": invert(scale(inputs.vix, 12.0, 32.0)),
    }
    composite = mean(list(components.values()))
    alt = altseason_lean(inputs.btc_change_7d, list(inputs.alt_changes_7d))
    return {
        "score": None if composite is None else round(composite, 1),
        "regime": regime_label(composite),
        "components": {
            key: None if value is None else round(value, 1) for key, value in components.items()
        },
        "divergence": same_day_divergence(inputs.btc_change_24h, inputs.spy_change_24h),
        "altseason": {
            "lean": None if alt["lean"] is None else round(alt["lean"], 2),
            "alts_beating_btc": None
            if alt["alts_beating_btc"] is None
            else round(alt["alts_beating_btc"], 1),
            "avg_alt_7d": None if alt["avg_alt_7d"] is None else round(alt["avg_alt_7d"], 2),
            "label": alt["label"],
        },
        "fear_greed_band": fear_greed_band(inputs.fear_greed),
        "btc_dominance": inputs.btc_dominance,
    }


def detect_events(
    *,
    previous_regime: str | None,
    health: dict[str, Any],
    btc_change_24h: float | None,
    vix: float | None,
    fear_greed: float | None,
    movers: list[tuple[str, float]],
) -> list[dict[str, str]]:
    """Return newly interesting market events from this snapshot."""
    events: list[dict[str, str]] = []
    regime = str(health.get("regime") or "unknown")
    if previous_regime and previous_regime != regime and regime != "unknown":
        events.append(
            {
                "kind": "regime-shift",
                "title": f"Regime → {regime}",
                "detail": f"Market health flipped from {previous_regime} to {regime}.",
            }
        )
    if btc_change_24h is not None and abs(btc_change_24h) >= 5:
        direction = "rip" if btc_change_24h > 0 else "dump"
        events.append(
            {
                "kind": "btc-move",
                "title": f"BTC {direction} {btc_change_24h:+.1f}%",
                "detail": "Bitcoin 24h move is large enough to reprice the whole board.",
            }
        )
    if vix is not None and vix >= 25:
        events.append(
            {
                "kind": "vix-spike",
                "title": f"VIX {vix:.1f}",
                "detail": "Equity fear is elevated — historically a headwind for risk assets including BTC.",
            }
        )
    band = str(health.get("fear_greed_band") or "")
    if fear_greed is not None and band in {"extreme-fear", "extreme-greed"}:
        events.append(
            {
                "kind": "sentiment",
                "title": f"Crypto {band.replace('-', ' ')} ({fear_greed:.0f})",
                "detail": "Sentiment is at an extreme. Mean-reversion setups get more interesting here.",
            }
        )
    divergence = health.get("divergence")
    if divergence in {"crypto-led", "equities-led"}:
        events.append(
            {
                "kind": "divergence",
                "title": f"BTC vs SPY: {divergence}",
                "detail": "Crypto and the S&P are not walking in lockstep today.",
            }
        )
    for symbol, change in movers:
        events.append(
            {
                "kind": "mover",
                "title": f"{symbol} {change:+.1f}%",
                "detail": "Outsized 24h move versus the rest of the board.",
            }
        )
    return events
