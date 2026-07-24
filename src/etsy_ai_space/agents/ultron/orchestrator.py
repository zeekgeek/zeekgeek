"""Ultron — master orchestrator for phased Etsy swarm execution."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from ...db import StoreDatabase
from ...models import CreativeBrief, ListingDraft
from ...tools.humanize import humanize_text
from .phases import run_phase1_research, run_phase2_brief, run_phase3_workers, run_phase4_export

LOGGER = logging.getLogger(__name__)


class UltronOrchestrator:
    """Coordinates researcher → brief → workers → export without live Etsy publishing."""

    def __init__(
        self,
        db: StoreDatabase,
        *,
        anthropic_api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        demo: bool = True,
        export_dir: str | None = None,
    ) -> None:
        self.db = db
        self.anthropic_api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.demo = demo
        self.export_dir = export_dir

    async def run_pipeline(
        self,
        query: str,
        *,
        niche: str | None = None,
        max_results: int = 48,
    ) -> dict[str, Any]:
        """Execute phases 1–4 in safe hybrid mode (export only, no API publish)."""
        research = await run_phase1_research(
            query,
            self.db,
            demo=self.demo,
            max_results=max_results,
        )
        brief = await run_phase2_brief(
            self.db,
            query=query,
            niche=niche or query,
            api_key=self.anthropic_api_key,
            model=self.model,
        )
        draft = await run_phase3_workers(
            self.db,
            brief,
            api_key=self.anthropic_api_key,
            model=self.model,
        )
        report = humanize_text(draft.title, draft.description, draft.tags)
        if not report.passed:
            draft.status = "needs_revision"
            LOGGER.warning("Humanization failed: %s", report.issues)
        else:
            draft.tags = report.cleaned_tags
            draft.status = "approved_for_export"
        saved = self.db.save_listing_draft(draft)
        export_paths = run_phase4_export(self.db, export_dir=self.export_dir)
        return {
            "research": research,
            "brief": brief.to_dict(),
            "draft": {
                "id": saved.id,
                "title": saved.title,
                "status": saved.status,
                "humanize": report.to_dict(),
            },
            "export": export_paths,
        }

    async def call_claude(self, system: str, user: str) -> str:
        """Optional Claude call for Phase 2/3 when ANTHROPIC_API_KEY is set."""
        if not self.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set — using template fallbacks.")
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("Install anthropic: pip install anthropic") from exc

        client = anthropic.Anthropic(api_key=self.anthropic_api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [block.text for block in message.content if hasattr(block, "text")]
        return "\n".join(parts).strip()

    @staticmethod
    def parse_json_response(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        return json.loads(text)
