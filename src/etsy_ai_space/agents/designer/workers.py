"""Designer worker agents — tags, SEO copy, and image prompts (template mode)."""

from __future__ import annotations

import re

from ...models import CreativeBrief, ListingDraft


def expand_listing_copy(brief: CreativeBrief) -> ListingDraft:
    """Deterministic fallback when Claude is unavailable."""
    niche_words = [word for word in re.findall(r"[a-zA-Z']+", brief.niche.lower()) if len(word) > 2]
    anchor = niche_words[0] if niche_words else "graphic"
    secondary = niche_words[1] if len(niche_words) > 1 else "vintage"

    title = f"{secondary.title()} {anchor.title()} Shirt | Original {brief.niche.title()} Tee"
    description = (
        f"Soft unisex tee featuring an original {brief.design_direction.lower()}. "
        f"Made for {brief.target_buyer.lower()} who want something specific—not another generic print. "
        f"Printed to order; ships from our partner facility.\n\n"
        f"Care: machine wash cold, inside out. Colors: {', '.join(brief.color_palette) or 'see mockup'}."
    )
    tags = _build_tags(brief, anchor, secondary)
    image_prompt = (
        f"Print-ready flat graphic for a t-shirt, {brief.design_direction}. "
        f"Palette: {', '.join(brief.color_palette) or 'warm retro tones'}. "
        f"No text, no logos, no copyrighted characters. Centered composition, transparent background."
    )
    return ListingDraft(
        brief_id=brief.id,
        title=title[:140],
        description=description,
        tags=tags,
        price=24.99,
        image_prompt=image_prompt,
        taxonomy_hint=f"Clothing > T-shirts > {brief.niche}",
    )


def _build_tags(brief: CreativeBrief, anchor: str, secondary: str) -> list[str]:
    base = [
        f"{anchor} shirt",
        f"{secondary} {anchor} tee",
        f"{anchor} lover gift",
        f"{secondary} graphic tee",
        f"{anchor} tshirt",
        "printed to order",
        "unisex tee",
        "original graphic shirt",
    ]
    for word in brief.color_palette[:2]:
        base.append(f"{word} aesthetic shirt")
    # Deduplicate while preserving order.
    seen: set[str] = set()
    tags: list[str] = []
    for tag in base:
        cleaned = tag.lower().strip()[:20]
        if cleaned in seen:
            continue
        seen.add(cleaned)
        tags.append(cleaned)
    return tags[:13]
