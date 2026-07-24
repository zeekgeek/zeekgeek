"""Phase helpers for the Ultron orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...db import StoreDatabase
from ...export.bundle import export_pending_drafts
from ...models import CreativeBrief, ListingDraft
from ..workers import expand_listing_copy
from ..researcher.runner import run_researcher, build_scraper


async def run_phase1_research(
    query: str,
    db: StoreDatabase,
    *,
    demo: bool,
    max_results: int,
) -> dict[str, object]:
    scraper = build_scraper(demo=demo)
    return await run_researcher(query, db, backend=scraper, max_results=max_results)


async def run_phase2_brief(
    db: StoreDatabase,
    *,
    query: str,
    niche: str,
    api_key: str | None,
    model: str,
) -> CreativeBrief:
    top = db.top_listings(limit=8)
    titles = [row["title"] for row in top[:5]]
    tags: list[str] = []
    for row in top[:5]:
        tags.extend(row.get("tags") or [])
    tag_sample = list(dict.fromkeys(tags))[:12]

    if api_key:
        from ..ultron.orchestrator import UltronOrchestrator

        orchestrator = UltronOrchestrator(db, anthropic_api_key=api_key, model=model)
        system = (
            "You are an Etsy POD trend analyst. Return ONLY valid JSON with keys: "
            "trend_summary, niche, target_buyer, design_direction, color_palette (array), avoid (array)."
        )
        user = json.dumps(
            {
                "search_query": query,
                "niche": niche,
                "top_titles": titles,
                "tag_signals": tag_sample,
                "instruction": "Propose an original, copyright-safe creative brief unlike the references.",
            },
            indent=2,
        )
        raw = await orchestrator.call_claude(system, user)
        payload = UltronOrchestrator.parse_json_response(raw)
        brief = CreativeBrief(
            trend_summary=str(payload.get("trend_summary", "")),
            niche=str(payload.get("niche", niche)),
            target_buyer=str(payload.get("target_buyer", "")),
            design_direction=str(payload.get("design_direction", "")),
            color_palette=list(payload.get("color_palette") or []),
            avoid=list(payload.get("avoid") or []),
            reference_listing_ids=[str(row.get("etsy_listing_id")) for row in top[:5] if row.get("etsy_listing_id")],
        )
    else:
        brief = CreativeBrief(
            trend_summary=f"Strong demand for '{niche}' with retro/minimal variants performing well.",
            niche=niche,
            target_buyer=f"Gift buyers and enthusiasts searching for {niche} on Etsy.",
            design_direction=(
                "Original line-art or retro sunset graphic with a specific hook — avoid copying reference titles."
            ),
            color_palette=["burnt orange", "cream", "forest green"],
            avoid=["generic slogans", "trademarked characters", "clip-art crowds"],
            reference_listing_ids=[str(row.get("etsy_listing_id")) for row in top[:5] if row.get("etsy_listing_id")],
        )

    saved = db.save_brief(brief)
    brief.id = saved.id
    _write_obsidian_note(db, brief, top)
    return brief


async def run_phase3_workers(
    db: StoreDatabase,
    brief: CreativeBrief,
    *,
    api_key: str | None,
    model: str,
) -> ListingDraft:
    if api_key:
        from ..ultron.orchestrator import UltronOrchestrator

        orchestrator = UltronOrchestrator(db, anthropic_api_key=api_key, model=model)
        system = (
            "You are an Etsy listing copywriter and POD art director. Return ONLY JSON with keys: "
            "title, description, tags (array, 8-13 specific tags), price (number), image_prompt."
        )
        user = json.dumps(brief.to_dict(), indent=2)
        raw = await orchestrator.call_claude(system, user)
        payload = UltronOrchestrator.parse_json_response(raw)
        return ListingDraft(
            brief_id=brief.id,
            title=str(payload["title"]),
            description=str(payload["description"]),
            tags=[str(tag) for tag in payload.get("tags") or []],
            price=float(payload.get("price") or 24.99),
            image_prompt=str(payload.get("image_prompt") or brief.design_direction),
            taxonomy_hint=brief.niche,
        )

    return expand_listing_copy(brief)


def run_phase4_export(db: StoreDatabase, *, export_dir: str | None) -> dict[str, str]:
    out_dir = Path(export_dir) if export_dir else Path.cwd() / "etsy_ai_space" / "exports"
    return export_pending_drafts(db, out_dir)


def _write_obsidian_note(db: StoreDatabase, brief: CreativeBrief, top: list[dict[str, Any]]) -> None:
    vault = Path.cwd() / "etsy_ai_space" / "obsidian_vault" / "briefs"
    vault.mkdir(parents=True, exist_ok=True)
    slug = brief.niche.lower().replace(" ", "-")[:48]
    path = vault / f"{slug}-{brief.id or 'draft'}.md"
    lines = [
        f"# Creative brief — {brief.niche}",
        "",
        f"**Trend summary:** {brief.trend_summary}",
        "",
        f"**Target buyer:** {brief.target_buyer}",
        "",
        f"**Design direction:** {brief.design_direction}",
        "",
        f"**Palette:** {', '.join(brief.color_palette)}",
        "",
        "## Reference signals",
    ]
    for row in top[:5]:
        lines.append(f"- {row.get('title')} (score={row.get('performance_score')})")
    lines.extend(["", "## Avoid", *[f"- {item}" for item in brief.avoid], ""])
    path.write_text("\n".join(lines), encoding="utf-8")
