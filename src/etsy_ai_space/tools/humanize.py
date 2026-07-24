"""Phase 3 quality gate — flag generic AI patterns before export."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


GENERIC_PHRASES = (
    r"\bperfect gift\b",
    r"\bunique design\b",
    r"\bhigh quality\b",
    r"\bmust have\b",
    r"\beye[- ]?catching\b",
    r"\bstand out\b",
    r"\bshow your personality\b",
    r"\bideal for\b",
    r"\bgreat for any occasion\b",
    r"\badd a touch of\b",
    r"\belevate your\b",
    r"\bdon't miss out\b",
    r"\bshop now\b",
    r"\blimited time\b",
    r"\b\d+\s*%\s*off\b",
)

TAG_BANNED = frozenset(
    {
        "gift",
        "unique",
        "trendy",
        "cool",
        "awesome",
        "best",
        "perfect",
        "custom",
        "personalized",
        "design",
    }
)


@dataclass
class HumanizeReport:
    passed: bool
    issues: list[str] = field(default_factory=list)
    cleaned_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issues": self.issues,
            "cleaned_tags": self.cleaned_tags,
        }


def humanize_text(
    title: str,
    description: str,
    tags: list[str],
    *,
    min_tag_count: int = 8,
    max_tag_count: int = 13,
) -> HumanizeReport:
    """Apply lightweight rules to reject boilerplate-heavy listing copy."""
    issues: list[str] = []
    combined = f"{title}\n{description}".lower()

    for pattern in GENERIC_PHRASES:
        if re.search(pattern, combined, flags=re.IGNORECASE):
            issues.append(f"Generic phrase detected: /{pattern}/")

    if len(title.strip()) < 12:
        issues.append("Title is too short — add specific niche detail.")
    if len(title) > 140:
        issues.append("Title exceeds Etsy-friendly length (~140 chars).")

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        tag = raw.strip().lower()[:20]
        if not tag or tag in seen:
            continue
        if tag in TAG_BANNED:
            issues.append(f"Tag too generic for Etsy SEO: '{tag}'")
            continue
        if " " in tag and len(tag.split()) > 3:
            issues.append(f"Tag too long or phrase-like: '{tag}'")
            continue
        seen.add(tag)
        cleaned.append(tag)

    if len(cleaned) < min_tag_count:
        issues.append(f"Need at least {min_tag_count} specific tags (got {len(cleaned)}).")
    if len(cleaned) > max_tag_count:
        issues.append(f"Too many tags ({len(cleaned)}); Etsy allows 13.")

    return HumanizeReport(passed=len(issues) == 0, issues=issues, cleaned_tags=cleaned)
