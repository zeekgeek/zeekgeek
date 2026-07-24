"""Pipeline orchestrator — manager agent analyzes trends and spawns worker output."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..agents.workers import workers_build_listing
from ..db import StoreDatabase, default_db_path
from ..export.bundle import export_pending_drafts
from ..models import ProductConcept
from ..scraper.etsy_scraper import scrape_niche_to_db
from ..tools.humanize import humanize_text

LOGGER = logging.getLogger(__name__)

CONCEPT_ANGLES = (
    "minimal line-art variant with a single bold silhouette",
    "retro sunset palette with distressed texture",
    "humor-forward quote layout with hand-lettered feel",
    "cottagecore nature motif with soft organic shapes",
    "bold typographic statement with high contrast",
)


class ManagerAgent:
    """Reads top listings and produces unique product concepts."""

    def __init__(self, *, anthropic_api_key: str | None = None, model: str = "claude-sonnet-4-20250514") -> None:
        self.api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model

    def analyze_trends(self, top_listings: list[dict[str, Any]]) -> str:
        if not top_listings:
            return "No listings in database yet — run the scraper first."

        titles = [row["title"] for row in top_listings[:8]]
        tags: list[str] = []
        for row in top_listings[:8]:
            tags.extend(row.get("tags") or [])
        top_tags = [tag for tag, _count in Counter(tags).most_common(6)]
        avg_price = sum(row.get("price_amount") or 0 for row in top_listings[:8]) / max(len(top_listings[:8]), 1)

        return (
            f"Top titles emphasize: {', '.join(titles[:3])}. "
            f"Tag signals: {', '.join(top_tags) or 'n/a'}. "
            f"Average price near ${avg_price:.2f}. "
            f"Winners mix specificity with gift-buyer language."
        )

    def generate_concepts(
        self,
        niche: str,
        top_listings: list[dict[str, Any]],
        *,
        count: int = 5,
    ) -> list[ProductConcept]:
        trend_summary = self.analyze_trends(top_listings)
        refs = [str(row["etsy_listing_id"]) for row in top_listings[:5] if row.get("etsy_listing_id")]
        niche_words = [word for word in re.findall(r"[a-zA-Z']+", niche.lower()) if len(word) > 2]
        anchor = niche_words[0] if niche_words else "graphic"
        secondary = niche_words[1] if len(niche_words) > 1 else "vintage"

        concepts: list[ProductConcept] = []
        for index, angle in enumerate(CONCEPT_ANGLES[:count]):
            variant = f"{secondary} {anchor}".title() if index % 2 == 0 else f"{anchor} {secondary}".title()
            concepts.append(
                ProductConcept(
                    concept_name=f"{variant} Concept {index + 1}",
                    hook=f"A fresh take on {niche} for buyers tired of copycat listings",
                    angle=angle,
                    trend_summary=trend_summary,
                    reference_listing_ids=refs,
                )
            )
        return concepts

    async def generate_concepts_with_claude(
        self,
        niche: str,
        top_listings: list[dict[str, Any]],
        *,
        count: int = 5,
    ) -> list[ProductConcept]:
        if not self.api_key:
            return self.generate_concepts(niche, top_listings, count=count)

        try:
            import anthropic
        except ImportError:
            return self.generate_concepts(niche, top_listings, count=count)

        trend_summary = self.analyze_trends(top_listings)
        client = anthropic.Anthropic(api_key=self.api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=1800,
            system=(
                "You are an Etsy POD trend manager. Return ONLY JSON: "
                '{"concepts":[{"concept_name","hook","angle"}, ...]} with exactly '
                f"{count} original, copyright-safe concepts unlike the references."
            ),
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "niche": niche,
                            "trend_summary": trend_summary,
                            "reference_titles": [row["title"] for row in top_listings[:8]],
                        },
                        indent=2,
                    ),
                }
            ],
        )
        raw = "\n".join(block.text for block in message.content if hasattr(block, "text"))
        if raw.strip().startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        payload = json.loads(raw)
        refs = [str(row["etsy_listing_id"]) for row in top_listings[:5] if row.get("etsy_listing_id")]
        return [
            ProductConcept(
                concept_name=str(item["concept_name"]),
                hook=str(item["hook"]),
                angle=str(item["angle"]),
                trend_summary=trend_summary,
                reference_listing_ids=refs,
            )
            for item in payload.get("concepts", [])[:count]
        ]


async def run_orchestrator(
    niche: str,
    db: StoreDatabase,
    *,
    demo: bool = False,
    max_results: int = 48,
    concept_count: int = 5,
    export_dir: Path | None = None,
    scrape_first: bool = True,
) -> dict[str, Any]:
    """Full pipeline: scrape → manager concepts → worker drafts → export bundle."""
    research: dict[str, object] | None = None
    if scrape_first:
        research = await scrape_niche_to_db(
            niche,
            db,
            demo=demo,
            max_results=max_results,
        )

    top = db.top_listings(limit=12)
    manager = ManagerAgent()
    concepts = await manager.generate_concepts_with_claude(niche, top, count=concept_count)

    saved_concepts: list[dict[str, Any]] = []
    drafts: list[dict[str, Any]] = []
    for concept in concepts:
        saved = db.save_concept(concept)
        concept.id = saved.id
        draft = workers_build_listing(concept)
        report = humanize_text(draft.title, draft.description, draft.tags)
        if report.passed:
            draft.tags = report.cleaned_tags
            draft.status = "approved_for_export"
        else:
            draft.status = "needs_revision"
        stored = db.save_listing_draft(draft)
        saved_concepts.append(concept.to_dict())
        drafts.append(
            {
                "id": stored.id,
                "concept": concept.concept_name,
                "title": draft.title,
                "status": draft.status,
                "humanize": report.to_dict(),
            }
        )

    out_dir = export_dir or Path.cwd() / "etsy_ai_space" / "exports"
    export_paths = export_pending_drafts(db, out_dir)

    return {
        "research": research,
        "trend_summary": manager.analyze_trends(top),
        "concepts": saved_concepts,
        "drafts": drafts,
        "export": export_paths,
    }


async def _cli(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    result = await run_orchestrator(
        args.niche,
        db,
        demo=args.demo,
        max_results=args.max_results,
        concept_count=args.concepts,
        export_dir=args.export_dir,
        scrape_first=not args.skip_scrape,
    )
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orchestrate scrape → concepts → worker drafts → export")
    parser.add_argument("niche", help="Niche query, e.g. 'retro cat shirt'")
    parser.add_argument("--db", type=Path, default=None, help=f"SQLite path (default: {default_db_path()})")
    parser.add_argument("--demo", action="store_true", help="Use demo scraper data")
    parser.add_argument("--max-results", type=int, default=48)
    parser.add_argument("--concepts", type=int, default=5, help="Number of product concepts to generate")
    parser.add_argument("--export-dir", type=Path, default=None)
    parser.add_argument("--skip-scrape", action="store_true", help="Use existing DB listings only")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    raise SystemExit(asyncio.run(_cli(args)))


if __name__ == "__main__":
    main()
