"""Specialized worker agents — copywriter, design (Midjourney), and SEO."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import ListingDraft, ProductConcept


@dataclass
class CopyOutput:
    title: str
    description: str


from .design_prompts import RECOVERY_KEYWORDS, build_recovery_design_brief


@dataclass
class DesignOutput:
    midjourney_prompt: str
    design_style: str = ""
    shirt_text: str = ""


@dataclass
class SeoOutput:
    tags: list[str]


# Buyer-facing Etsy titles per design style (max 140 chars each).
_STYLE_TITLES = {
    "definition": "Recovery Definition Shirt, Dictionary Style Sobriety Tee, Sober Anniversary Gift",
    "minimal": "We Do Recover Shirt, Minimalist Sobriety Tee, Recovery Gift for Her or Him",
    "odaat": "One Day at a Time Shirt, ODAAT Recovery Tee, Sobriety Milestone Gift",
    "advocacy": "Recover Out Loud Shirt, Recovery Advocacy Tee, Sober Support Gift",
    "soberversary": "Custom Soberversary Shirt, Personalized Sober Anniversary Date Tee, Recovery Milestone Gift",
    "varsity": "Recovery Crew Shirt, Varsity Style Sobriety Tee, Sober Squad Gift",
    "namastay": "Namastay Sober Shirt, Yoga Recovery Tee, Funny Sobriety Gift",
    "journey": "Recovery Is a Journey Shirt, Inspirational Sobriety Tee, Sober Encouragement Gift",
    "reason": "Recovery Is Possible Shirt, Motivational Sober Tee, Recovery Awareness Gift",
}


def _is_recovery_concept(concept: ProductConcept) -> bool:
    blob = f"{concept.concept_name} {concept.hook} {concept.angle}".lower()
    return any(keyword in blob for keyword in RECOVERY_KEYWORDS)


def _clean_concept_name(name: str) -> str:
    """Strip internal scaffolding like 'Concept 3' from buyer-facing text."""
    cleaned = re.sub(r"\bconcept\s*\d*\b", "", name, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" |-")


def copywriter_agent(concept: ProductConcept, *, price: float = 24.99) -> CopyOutput:
    """Rewrite trend hooks into Etsy-ready title and description."""
    if _is_recovery_concept(concept):
        brief = build_recovery_design_brief(concept)
        title = _STYLE_TITLES[brief.style][:140]
        shirt_line = brief.shirt_text.replace("\n", " ").replace("  ", " ")
        personalize = (
            "Add your sobriety date at checkout and the design is personalized before printing.\n\n"
            if brief.style == "soberversary"
            else ""
        )
        description = (
            f"\u201c{shirt_line}\u201d\n\n"
            "Original typography design created for the recovery community — "
            "a meaningful piece for sober anniversaries, milestones, and anyone "
            "choosing themselves one day at a time.\n\n"
            f"{personalize}"
            "• Printed to order on a soft unisex tee\n"
            "• True-to-size unisex fit — size up for an oversized look\n"
            "• Machine wash cold, inside out; tumble dry low\n\n"
            "Design created with AI-assisted tools and finished by hand."
        )
        return CopyOutput(title=title, description=description)

    name = _clean_concept_name(concept.concept_name) or concept.concept_name.strip()
    base = re.sub(r"\b(shirt|tee|t-shirt)\b", "", name, flags=re.IGNORECASE)
    base = re.sub(r"\s{2,}", " ", base).strip()
    title = f"{base.title()} Shirt, Unisex Graphic Tee, Printed to Order"[:140]
    description = (
        f"{concept.angle.strip()}\n\n"
        "An original graphic tee for buyers who want something specific — not a generic print. "
        "Printed to order on a soft unisex shirt.\n\n"
        "Care: machine wash cold, inside out. Tumble dry low.\n"
        "Design created with AI-assisted tools and finished by hand."
    )
    return CopyOutput(title=title, description=description)


def design_agent(concept: ProductConcept) -> DesignOutput:
    """Create Canva + AI art briefs for recovery typography shirts."""
    brief = build_recovery_design_brief(concept)
    return DesignOutput(
        midjourney_prompt=brief.to_image_prompt(),
        design_style=brief.style,
        shirt_text=brief.shirt_text,
    )


# Recovery buyer-search vocabulary (each ≤ 20 chars, Etsy's tag limit).
_RECOVERY_TAG_POOL = (
    "sobriety gift",
    "recovery shirt",
    "sober anniversary",
    "soberversary gift",
    "recovery gift",
    "sober living",
    "one day at a time",
    "addiction recovery",
    "mental health tee",
    "sober gift for her",
    "sober gift for him",
)

_STYLE_TAGS = {
    "definition": ("dictionary tee", "definition shirt"),
    "minimal": ("we do recover", "minimalist tee"),
    "odaat": ("odaat shirt", "sober milestone"),
    "advocacy": ("recover out loud", "recovery advocate"),
    "soberversary": ("custom sober date", "personalized gift"),
    "varsity": ("sober crew shirt", "varsity style tee"),
    "namastay": ("namastay sober", "yoga recovery tee"),
    "journey": ("recovery journey", "inspirational tee"),
    "reason": ("recovery possible", "motivational tee"),
}

_TAG_STOPWORDS = {"the", "and", "for", "with", "concept", "shirt", "tee"}


def seo_agent(concept: ProductConcept, title: str, *, design_style: str = "") -> SeoOutput:
    """Generate optimized Etsy tags from concept + title tokens."""
    tags: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        cleaned = " ".join(tag.lower().split())
        if not cleaned or len(cleaned) > 20:
            # Etsy rejects tags over 20 chars; skipping beats truncating mid-word.
            return
        if cleaned not in seen:
            seen.add(cleaned)
            tags.append(cleaned)

    if _is_recovery_concept(concept):
        # Style tags are recovery-themed, so gate them on recovery concepts.
        for tag in _STYLE_TAGS.get(design_style, ()):
            add(tag)
        for tag in _RECOVERY_TAG_POOL:
            if len(tags) >= 13:
                break
            add(tag)

    words = re.findall(r"[a-zA-Z']+", f"{concept.concept_name} {title} {concept.hook}".lower())
    tokens = [word for word in words if len(word) > 2 and word not in _TAG_STOPWORDS]
    for token in tokens[:4]:
        add(f"{token} shirt")
        add(f"{token} tee")

    add("printed to order")
    add("unisex graphic tee")
    add("original design tee")

    niche_bits = [
        word for word in _clean_concept_name(concept.concept_name).lower().split() if word not in _TAG_STOPWORDS
    ][:2]
    if niche_bits:
        add(f"{' '.join(niche_bits)} gift")

    return SeoOutput(tags=tags[:13])


def workers_build_listing(concept: ProductConcept, *, price: float = 24.99) -> ListingDraft:
    """Run all three workers and assemble a listing draft."""
    copy = copywriter_agent(concept, price=price)
    design = design_agent(concept)
    seo = seo_agent(concept, copy.title, design_style=design.design_style)
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
