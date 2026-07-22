"""Heuristic detection of threatening, coercive, and abusive language."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

ThreatLevel = Literal["none", "low", "medium", "high", "critical"]

_CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    (
        "physical_threat",
        re.compile(
            r"\b("
            r"kill|murder|beat\s*(you|the\s*shit)|hurt\s*you|break\s*your|"
            r"punch|stab|shoot|strangle|choke|slap|burn\s*you|"
            r"end\s*you|make\s*you\s*pay|watch\s*your\s*back"
            r")\b",
            re.I,
        ),
        35,
    ),
    (
        "coercion_control",
        re.compile(
            r"\b("
            r"or\s*else|you\s*better|don'?t\s*make\s*me|last\s*warning|"
            r"you\s*owe\s*me|do\s*what\s*i\s*say|nobody\s*else|"
            r"can'?t\s*leave|where\s*are\s*you|who\s*are\s*you\s*with|"
            r"answer\s*me\s*now|pick\s*up\s*the\s*phone"
            r")\b",
            re.I,
        ),
        22,
    ),
    (
        "intimidation",
        re.compile(
            r"\b("
            r"i\s*know\s*where|come\s*over\s*here|open\s*the\s*door|"
            r"outside\s*your|waiting\s*for\s*you|find\s*you|"
            r"regret\s*this|you'?ll\s*be\s*sorry|remember\s*this"
            r")\b",
            re.I,
        ),
        28,
    ),
    (
        "harassment_insult",
        re.compile(
            r"\b("
            r"bitch|whore|slut|stupid|worthless|pathetic|trash|"
            r"nobody\s*wants\s*you|ugly|crazy\s*bitch|psycho"
            r")\b",
            re.I,
        ),
        18,
    ),
    (
        "sexual_coercion",
        re.compile(
            r"\b("
            r"you\s*owe\s*me\s*sex|spread\s*your|nudes|send\s*pics|"
            r"sleep\s*with\s*me\s*or"
            r")\b",
            re.I,
        ),
        30,
    ),
    (
        "self_harm_manipulation",
        re.compile(
            r"\b("
            r"kill\s*myself\s*if|hurt\s*myself\s*because|"
            r"your\s*fault\s*if\s*i|blame\s*you\s*if"
            r")\b",
            re.I,
        ),
        25,
    ),
]

_ALL_CAPS_SHOUT = re.compile(r"[A-Z]{8,}")
_EXCESS_PUNCT = re.compile(r"[!?]{3,}")


@dataclass(frozen=True)
class ThreatAssessment:
    level: ThreatLevel
    score: int
    categories: tuple[str, ...]
    matched_phrases: tuple[str, ...]
    shield_recommended: bool

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "score": self.score,
            "categories": list(self.categories),
            "matched_phrases": list(self.matched_phrases),
            "shield_recommended": self.shield_recommended,
        }


@dataclass
class _Accumulator:
    score: int = 0
    categories: set[str] = field(default_factory=set)
    phrases: list[str] = field(default_factory=list)


def assess_message(text: str, *, prior_escalation: int = 0) -> ThreatAssessment:
    """Score a single inbound message. prior_escalation adds weight from recent history."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ThreatAssessment("none", 0, (), (), False)

    acc = _Accumulator()
    lower = cleaned.lower()

    for name, pattern, weight in _CATEGORY_PATTERNS:
        for match in pattern.finditer(cleaned):
            acc.score += weight
            acc.categories.add(name)
            snippet = match.group(0).strip()
            if snippet and snippet.lower() not in {p.lower() for p in acc.phrases}:
                acc.phrases.append(snippet)

    if _ALL_CAPS_SHOUT.search(cleaned):
        acc.score += 8
        acc.categories.add("shouting")
    if _EXCESS_PUNCT.search(cleaned):
        acc.score += 5
        acc.categories.add("aggressive_tone")

    # Repeated short demands
    if len(cleaned) < 120 and cleaned.endswith("?") and "answer" in lower:
        acc.score += 6

    total = min(100, acc.score + min(prior_escalation, 40))
    level = _score_to_level(total)
    shield = level in ("medium", "high", "critical") or total >= 28

    return ThreatAssessment(
        level=level,
        score=total,
        categories=tuple(sorted(acc.categories)),
        matched_phrases=tuple(acc.phrases[:12]),
        shield_recommended=shield,
    )


def _score_to_level(score: int) -> ThreatLevel:
    if score >= 70:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 28:
        return "medium"
    if score >= 12:
        return "low"
    return "none"


def combine_recent_escalation(scores: list[int], window: int = 6) -> int:
    """Sum recent threat scores with decay for time-sink activation."""
    if not scores:
        return 0
    tail = scores[-window:]
    return sum(tail) // max(1, len(tail))
