"""Specialized worker agents — copywriter, design (Midjourney), and SEO."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import ListingDraft, ProductConcept


@dataclass
class CopyOutput:
    title: str
    description: str


@dataclass
class DesignOutput:
    midjourney_prompt: str


@dataclass
class SeoOutput:
    tags: list[str]


def copywriter_agent(concept: ProductConcept, *, price: float = 24.99) -> CopyOutput:
    """Rewrite trend hooks into Etsy-ready title and description."""
    name = concept.concept_name.strip()
    hook = concept.hook.strip()
    angle = concept.angle.strip()

    title = f"{name} | {hook}"[:140]
    description = (
        f"{angle}\n\n"
        f"This original graphic tee speaks to buyers who want something specific—not a generic print. "
        f"{hook}. Printed to order on a soft unisex shirt.\n\n"
        f"Care: machine wash cold, inside out. Tumble dry low.\n"
        f"Price point: ${price:.2f}."
    )
    return CopyOutput(title=title, description=description)


def design_agent(concept: ProductConcept) -> DesignOutput:
    """Create a Midjourney-ready prompt from a product concept."""
    palette = "warm retro tones, cream, burnt orange"
    prompt = (
        f"Print-ready flat t-shirt graphic, {concept.concept_name.lower()}, {concept.angle.lower()}, "
        f"{concept.hook.lower()}, {palette}, centered composition, clean vector style, "
        f"no text, no logos, no copyrighted characters, transparent background --ar 1:1 --style raw"
    )
    return DesignOutput(midjourney_prompt=prompt)


def seo_agent(concept: ProductConcept, title: str) -> SeoOutput:
    """Generate optimized Etsy tags from concept + title tokens."""
    words = re.findall(r"[a-zA-Z']+", f"{concept.concept_name} {title} {concept.hook}".lower())
    tokens = [word for word in words if len(word) > 2 and word not in {"the", "and", "for", "with"}]

    tags: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        cleaned = tag.lower().strip()[:20]
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            tags.append(cleaned)

    for token in tokens[:4]:
        add(f"{token} shirt")
        add(f"{token} tee")

    add("printed to order")
    add("unisex graphic tee")
    add("original design shirt")

    niche_bits = concept.concept_name.lower().split()[:2]
    if niche_bits:
        add(f"{' '.join(niche_bits)} gift")

    return SeoOutput(tags=tags[:13])


def workers_build_listing(concept: ProductConcept, *, price: float = 24.99) -> ListingDraft:
    """Run all three workers and assemble a listing draft."""
    copy = copywriter_agent(concept, price=price)
    design = design_agent(concept)
    seo = seo_agent(concept, copy.title)
    return ListingDraft(
        concept_id=concept.id,
        title=copy.title,
        description=copy.description,
        tags=seo.tags,
        price=price,
        image_prompt=design.midjourney_prompt,
        taxonomy_hint=concept.concept_name,
    )


def expand_listing_copy(brief) -> ListingDraft:
    """Backward-compatible wrapper for legacy CreativeBrief pipeline."""
    concept = ProductConcept(
        concept_name=brief.niche,
        hook=brief.design_direction[:80],
        angle=brief.target_buyer,
        trend_summary=brief.trend_summary,
        reference_listing_ids=brief.reference_listing_ids,
    )
    return workers_build_listing(concept)
