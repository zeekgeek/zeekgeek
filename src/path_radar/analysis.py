"""Hop latency stats, introduced-delay detection, and path grading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

SLOW_ADDED_MS = 25.0
WARN_ADDED_MS = 12.0
SLOW_RTT_MS = 120.0
LOSS_WARN_PCT = 5.0
LOSS_BAD_PCT = 15.0
EXCELLENT_E2E_MS = 25.0
GOOD_E2E_MS = 60.0


@dataclass(frozen=True)
class LatencyStats:
    current_ms: float | None
    min_ms: float | None
    avg_ms: float | None
    max_ms: float | None
    jitter_ms: float | None
    loss_pct: float
    count: int
    timeouts: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "current_ms": _round(self.current_ms),
            "min_ms": _round(self.min_ms),
            "avg_ms": _round(self.avg_ms),
            "max_ms": _round(self.max_ms),
            "jitter_ms": _round(self.jitter_ms),
            "loss_pct": _round(self.loss_pct, 1),
            "count": self.count,
            "timeouts": self.timeouts,
        }


@dataclass(frozen=True)
class HopReading:
    """One hop on a path, with cumulative RTT (PingPlotter-style)."""

    hop: int
    ip: str | None
    hostname: str | None
    rtt_ms: float | None
    loss_pct: float = 0.0
    timed_out: bool = False


@dataclass(frozen=True)
class ClassifiedHop:
    hop: int
    ip: str | None
    hostname: str | None
    rtt_ms: float | None
    added_ms: float | None
    loss_pct: float
    health: str
    timed_out: bool
    filtered: bool
    reason: str | None


@dataclass(frozen=True)
class ProblemHop:
    hop: int
    ip: str | None
    hostname: str | None
    kind: str
    health: str
    severity: int
    added_ms: float | None
    rtt_ms: float | None
    loss_pct: float
    reason: str
    node_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "hop": self.hop,
            "ip": self.ip,
            "hostname": self.hostname,
            "kind": self.kind,
            "health": self.health,
            "severity": self.severity,
            "added_ms": _round(self.added_ms),
            "rtt_ms": _round(self.rtt_ms),
            "loss_pct": _round(self.loss_pct, 1),
            "reason": self.reason,
            "node_id": self.node_id,
        }


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def summarize(samples: Sequence[float | None]) -> LatencyStats:
    """Min/avg/max/jitter/loss over a hop's recent probe history."""
    count = len(samples)
    timeouts = sum(1 for sample in samples if sample is None)
    values = [float(sample) for sample in samples if sample is not None]
    loss_pct = (100.0 * timeouts / count) if count else 0.0
    if not values:
        return LatencyStats(
            current_ms=None,
            min_ms=None,
            avg_ms=None,
            max_ms=None,
            jitter_ms=None,
            loss_pct=loss_pct,
            count=count,
            timeouts=timeouts,
        )
    diffs = [abs(values[index] - values[index - 1]) for index in range(1, len(values))]
    jitter = sum(diffs) / len(diffs) if diffs else 0.0
    return LatencyStats(
        current_ms=values[-1],
        min_ms=min(values),
        avg_ms=sum(values) / len(values),
        max_ms=max(values),
        jitter_ms=jitter,
        loss_pct=loss_pct,
        count=count,
        timeouts=timeouts,
    )


def introduced_ms(current_rtt: float | None, previous_rtt: float | None) -> float | None:
    """Latency added at this hop versus the previous responding hop."""
    if current_rtt is None or previous_rtt is None:
        return None
    return max(0.0, float(current_rtt) - float(previous_rtt))


def classify_hops(readings: Sequence[HopReading]) -> list[ClassifiedHop]:
    """Label each hop: ok, warn, slow, loss, timeout, or ICMP-filtered."""
    later_ok = [False] * len(readings)
    seen_ok = False
    for index in range(len(readings) - 1, -1, -1):
        later_ok[index] = seen_ok
        if readings[index].rtt_ms is not None and not readings[index].timed_out:
            seen_ok = True

    classified: list[ClassifiedHop] = []
    previous_rtt = 0.0
    for index, reading in enumerate(readings):
        timed_out = reading.timed_out or reading.rtt_ms is None
        added = None if timed_out else introduced_ms(reading.rtt_ms, previous_rtt)
        filtered = timed_out and later_ok[index]
        health, reason = _health(
            timed_out=timed_out,
            filtered=filtered,
            added_ms=added,
            rtt_ms=reading.rtt_ms,
            loss_pct=reading.loss_pct,
        )
        classified.append(
            ClassifiedHop(
                hop=reading.hop,
                ip=reading.ip,
                hostname=reading.hostname,
                rtt_ms=None if timed_out else reading.rtt_ms,
                added_ms=added,
                loss_pct=reading.loss_pct,
                health=health,
                timed_out=timed_out,
                filtered=filtered,
                reason=reason,
            )
        )
        if not timed_out and reading.rtt_ms is not None:
            previous_rtt = float(reading.rtt_ms)
    return classified


def _health(
    *,
    timed_out: bool,
    filtered: bool,
    added_ms: float | None,
    rtt_ms: float | None,
    loss_pct: float,
) -> tuple[str, str | None]:
    if timed_out and filtered:
        return "filtered", "No ICMP from this router, but later hops still reply (rate-limit / filter)."
    if timed_out:
        return "timeout", "Hop timed out; nothing beyond this point replied."
    if loss_pct >= LOSS_BAD_PCT:
        return "loss", f"Packet loss {loss_pct:.0f}% — this router is dropping probes."
    if added_ms is not None and added_ms >= SLOW_ADDED_MS:
        return "slow", f"This hop introduced {added_ms:.0f} ms of extra delay."
    if rtt_ms is not None and rtt_ms >= SLOW_RTT_MS and (added_ms or 0) >= WARN_ADDED_MS:
        return "slow", f"Cumulative RTT {rtt_ms:.0f} ms with a jump at this hop."
    if loss_pct >= LOSS_WARN_PCT:
        return "warn", f"Elevated loss {loss_pct:.0f}%."
    if added_ms is not None and added_ms >= WARN_ADDED_MS:
        return "warn", f"This hop added {added_ms:.0f} ms."
    return "ok", None


def find_problems(classified: Sequence[ClassifiedHop]) -> list[ProblemHop]:
    """Hops that introduce delay, loss, or a hard timeout — not ICMP-filtered hops."""
    problems: list[ProblemHop] = []
    for item in classified:
        if item.health in {"ok", "warn", "filtered"}:
            continue
        severity = {"slow": 2, "loss": 3, "timeout": 4}.get(item.health, 1)
        if item.health == "slow" and (item.added_ms or 0) >= 70:
            severity = 3
        problems.append(
            ProblemHop(
                hop=item.hop,
                ip=item.ip,
                hostname=item.hostname,
                kind=item.health,
                health=item.health,
                severity=severity,
                added_ms=item.added_ms,
                rtt_ms=item.rtt_ms,
                loss_pct=item.loss_pct,
                reason=item.reason or item.health,
                node_id=_node_id(item.ip, item.hop),
            )
        )
    problems.sort(key=lambda item: (-item.severity, -(item.added_ms or 0), -item.loss_pct, item.hop))
    return problems


def end_to_end_ms(classified: Sequence[ClassifiedHop]) -> float | None:
    for item in reversed(classified):
        if item.rtt_ms is not None:
            return float(item.rtt_ms)
    return None


def grade_path(classified: Sequence[ClassifiedHop], problems: Sequence[ProblemHop]) -> str:
    e2e = end_to_end_ms(classified)
    if e2e is None:
        return "down"
    kinds = {problem.kind for problem in problems}
    if "timeout" in kinds:
        return "critical"
    if "loss" in kinds:
        return "poor"
    if "slow" in kinds:
        return "poor" if e2e >= 150 else "fair"
    loss = max((item.loss_pct for item in classified), default=0.0)
    if e2e <= EXCELLENT_E2E_MS and loss < 1:
        return "excellent"
    if e2e <= GOOD_E2E_MS and loss < LOSS_WARN_PCT:
        return "good"
    return "fair"


def _node_id(ip: str | None, hop: int) -> str:
    from .topology import node_id_for

    return node_id_for(ip, hop)
