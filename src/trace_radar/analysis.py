"""Hop-path analysis: introduced latency, slow hops, and problem routers.

PingPlotter-style scoring looks at *where latency enters the path* (the delta
versus the previous responding hop) rather than blaming every downstream hop
that inherits a high RTT.
"""

from __future__ import annotations

from typing import Any

SLOW_ADDED_MS = 25.0
SLOW_RTT_MS = 150.0
LOSS_WARN_PCT = 5.0
LOSS_BAD_PCT = 20.0


def annotate_hops(hops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return hop dicts with added_ms, icmp_filtered, slow, and problem_reason."""
    n = len(hops)
    later_ok = [False] * n
    seen = False
    for index in range(n - 1, -1, -1):
        later_ok[index] = seen
        if hops[index].get("responded") and hops[index].get("rtt_avg_ms") is not None:
            seen = True

    prev_rtt: float | None = 0.0
    annotated: list[dict[str, Any]] = []
    for index, hop in enumerate(hops):
        item = dict(hop)
        rtt = item.get("rtt_avg_ms")
        responded = bool(item.get("responded"))
        last_loss = float(item.get("last_loss_pct") or 0.0)
        icmp_filtered = (not responded or last_loss >= 100.0) and later_ok[index]
        added: float | None = None
        if rtt is not None and prev_rtt is not None:
            added = round(max(0.0, float(rtt) - prev_rtt), 2)
        item["added_ms"] = added
        item["icmp_filtered"] = icmp_filtered

        reason: str | None = None
        if icmp_filtered:
            reason = None
        elif not responded:
            reason = "timeout"
        elif added is not None and added >= SLOW_ADDED_MS:
            reason = "latency-introduced"
        elif last_loss >= LOSS_BAD_PCT:
            reason = "high-loss"
        elif rtt is not None and float(rtt) >= SLOW_RTT_MS and (added or 0) >= 12:
            reason = "latency-introduced"
        elif last_loss >= LOSS_WARN_PCT:
            reason = "loss-warn"

        item["problem_reason"] = reason
        item["slow"] = reason in {"latency-introduced", "high-loss", "timeout"}
        if item["slow"] and item.get("health") == "good":
            item["health"] = "degraded"
        if rtt is not None:
            prev_rtt = float(rtt)
        annotated.append(item)
    return annotated


def problem_cards(hops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact provider cards for hops that actually degrade the path."""
    cards: list[dict[str, Any]] = []
    for hop in hops:
        reason = hop.get("problem_reason")
        if not reason or hop.get("icmp_filtered") or reason == "loss-warn":
            continue
        whois = hop.get("whois") or {}
        geo = hop.get("geo") or {}
        provider = (
            whois.get("org")
            or whois.get("registrant")
            or geo.get("isp")
            or geo.get("org")
            or ("Private network" if hop.get("is_private") else None)
        )
        cards.append(
            {
                "ttl": hop.get("ttl"),
                "ip": hop.get("ip"),
                "hostname": hop.get("hostname"),
                "reason": reason,
                "added_ms": hop.get("added_ms"),
                "rtt_avg_ms": hop.get("rtt_avg_ms"),
                "rtt_last_ms": hop.get("rtt_last_ms"),
                "loss_pct": hop.get("last_loss_pct"),
                "health": hop.get("health"),
                "provider": provider,
                "asn": whois.get("asn") or geo.get("asn"),
                "cidr": whois.get("cidr"),
                "network": whois.get("name") or whois.get("handle"),
                "city": geo.get("city"),
                "country": geo.get("country") or whois.get("country"),
                "place": geo.get("place"),
                "abuse_email": whois.get("abuse_email"),
                "abuse_phone": whois.get("abuse_phone"),
                "summary": whois.get("summary"),
                "detail": _problem_detail(hop, whois, geo, provider),
            }
        )
    return cards


def _problem_detail(
    hop: dict[str, Any],
    whois: dict[str, Any],
    geo: dict[str, Any],
    provider: str | None,
) -> str:
    bits: list[str] = []
    added = hop.get("added_ms")
    if hop.get("problem_reason") == "timeout":
        bits.append("This hop did not answer ICMP/UDP probes.")
    elif added:
        bits.append(f"This hop added {added:.0f} ms of latency to the path.")
    loss = hop.get("last_loss_pct") or 0
    if loss:
        bits.append(f"Last cycle packet loss {loss:.0f}%.")
    place = geo.get("place") or ", ".join(p for p in (geo.get("city"), geo.get("country")) if p)
    if provider and place:
        bits.append(f"Router appears to be {provider} in {place}.")
    elif provider:
        bits.append(f"Router operator: {provider}.")
    if whois.get("cidr"):
        bits.append(f"Announced prefix {whois['cidr']}.")
    if whois.get("asn"):
        bits.append(f"ASN {whois['asn']}.")
    if whois.get("abuse_email"):
        bits.append(f"Abuse contact {whois['abuse_email']}.")
    return " ".join(bits) or "Degraded hop with limited ownership data."
