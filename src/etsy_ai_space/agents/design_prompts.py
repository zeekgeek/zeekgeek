"""Recovery-niche POD design briefs — typography-first (matches top Etsy winners)."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import ProductConcept

RECOVERY_KEYWORDS = ("recovery", "sober", "sobriety", "odaat", "soberversary", "namastay")

# Original wording only — do not copy competitor listing text verbatim.
ORIGINAL_PHRASES = {
    "definition": (
        "recovery | ri-kuhv-uh-ree | noun\n"
        "the act of regaining what was lost.\n"
        "choosing yourself, one brave decision at a time."
    ),
    "minimal": "we do recover.",
    "odaat": "one day\nat a time",
    "advocacy": "when we recover out loud,\nwe help others find hope.",
    "soberversary": "est. [CUSTOM DATE]\nsoberversary",
    "varsity": "RECOVERY\nCREW",
    "namastay": "namastay sober",
    "journey": "recovery is a journey,\nnot a destination.",
    "reason": "be the reason\nsomeone believes\nrecovery is possible.",
}


@dataclass
class DesignBrief:
    """Actionable art direction for Canva (primary) and AI tools (secondary)."""

    style: str
    shirt_text: str
    canva_steps: str
    ideogram_prompt: str
    midjourney_prompt: str

    def to_image_prompt(self) -> str:
        """Single export field with copy-paste sections for each tool."""
        return (
            f"=== STYLE: {self.style} ===\n\n"
            f"SHIRT TEXT (type this exactly in Canva):\n{self.shirt_text}\n\n"
            f"--- CANVA (recommended for text shirts) ---\n{self.canva_steps}\n\n"
            f"--- IDEOGRAM (good AI text rendering) ---\n{self.ideogram_prompt}\n\n"
            f"--- MIDJOURNEY (icons/texture only — fix text in Canva) ---\n"
            f"{self.midjourney_prompt}\n"
        )


_STYLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("namastay", ("namastay", "yoga")),
    ("varsity", ("crew", "varsity")),
    ("soberversary", ("soberversary", "milestone", "anniversary", "custom date", "date stamp")),
    ("odaat", ("one day", "odaat")),
    ("advocacy", ("loudly", "advocacy", "out loud")),
    ("journey", ("journey", "peace")),
    ("reason", ("reason", "possible")),
    ("minimal", ("minimal", "script", "we do recover")),
    ("definition", ("definition", "dictionary")),
)


def _match_style(text: str) -> str | None:
    for style, keywords in _STYLE_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return style
    return None


def _pick_style(concept: ProductConcept) -> str:
    # The angle carries the intended art direction, so it wins over niche words
    # that leak into every concept name (e.g. "definition" in a definition-niche
    # run must not force all five concepts into the same design).
    style = _match_style(concept.angle.lower())
    if style:
        return style
    blob = f"{concept.concept_name} {concept.hook} {concept.trend_summary}".lower()
    style = _match_style(blob)
    if style:
        return style
    if "typographic" in blob or "bold" in blob:
        return "minimal"
    return "definition"


def build_recovery_design_brief(concept: ProductConcept) -> DesignBrief:
    """Build a typography-first design brief for recovery POD."""
    style = _pick_style(concept)
    shirt_text = ORIGINAL_PHRASES[style]
    niche = concept.concept_name.replace("Concept", "").strip()

    canva_base = (
        "1. Canva → Custom size 4500×5400 px (Printful/Printify print file)\n"
        "2. Transparent background\n"
        "3. One centered text block, high contrast (white on dark or black on light)\n"
        "4. Export PNG\n"
        "5. Upload to Printful → mockup → Etsy listing\n"
    )

    style_fonts = {
        "definition": "Font: classic serif dictionary style (e.g. Libre Baskerville). Left-aligned blocks.",
        "minimal": "Font: thin elegant script + small caps sans subtitle. Lots of negative space.",
        "odaat": "Font: bold condensed sans for numbers, lighter sans for 'at a time'.",
        "advocacy": "Font: bold distressed sans, 2–3 lines, centered.",
        "soberversary": "Font: typewriter or stamp date on top, clean sans below. Leave [CUSTOM DATE] for orders.",
        "varsity": "Font: collegiate arch 'RECOVERY' over block 'CREW'.",
        "namastay": "Font: playful rounded sans, yoga-studio aesthetic.",
        "journey": "Font: soft serif, centered, calm palette.",
        "reason": "Font: mixed weights — light intro line, bold 'recovery is possible'.",
    }

    canva_steps = canva_base + style_fonts[style]

    ideogram_prompt = (
        f"T-shirt design PNG, transparent background, centered typography only, "
        f"text reads exactly: '{shirt_text.replace(chr(10), ' / ')}', "
        f"{style} style, print-ready, no mockup, no shirt visible, 4500x5400"
    )

    midjourney_prompt = (
        f"Minimal POD graphic element for {niche}, {concept.angle}, "
        f"subtle texture or small icon supporting recovery theme, NO TEXT, NO WORDS, "
        f"transparent background, centered, clean vector --ar 1:1 --style raw"
    )

    return DesignBrief(
        style=style,
        shirt_text=shirt_text,
        canva_steps=canva_steps,
        ideogram_prompt=ideogram_prompt,
        midjourney_prompt=midjourney_prompt,
    )
