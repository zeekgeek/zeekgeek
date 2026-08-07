"""Autonomous pipeline runner — schedule → concepts → image → Printify publish."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..db import StoreDatabase
from ..pipeline.orchestrator import run_orchestrator
from ..pipeline.state_tracker import SwarmStateTracker

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.cwd() / "etsy_ai_space" / "autopilot.yaml"


@dataclass
class AutopilotConfig:
    niches: list[str]
    cycle_interval_seconds: float = 21600.0
    max_cycles_per_day: int = 4
    concepts_per_cycle: int = 5
    max_results_per_scrape: int = 24
    demo: bool = True
    use_claude: bool = False
    require_manual_upload: bool = True
    daily_upload_cap: int = 5
    # n8n-style continuation after research/export
    auto_approve: bool = False
    auto_generate_images: bool = False
    auto_printify: bool = False
    printify_publish: bool = False
    uploads_per_cycle: int = 2
    image_provider: str = "openai"
    openai_image_model: str = "gpt-image-1"
    openai_image_size: str = "1024x1024"
    openai_image_quality: str = "medium"
    printify: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> AutopilotConfig:
        config_path = path or DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return cls(niches=["retro cat shirt"], demo=True)
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        niches = raw.get("niches") or ["retro cat shirt"]
        printify_raw = raw.get("printify") if isinstance(raw.get("printify"), dict) else {}
        return cls(
            niches=[str(n) for n in niches],
            cycle_interval_seconds=float(raw.get("cycle_interval_seconds", 21600)),
            max_cycles_per_day=int(raw.get("max_cycles_per_day", 4)),
            concepts_per_cycle=int(raw.get("concepts_per_cycle", 5)),
            max_results_per_scrape=int(raw.get("max_results_per_scrape", 24)),
            demo=bool(raw.get("demo", True)),
            use_claude=bool(raw.get("use_claude", False)),
            require_manual_upload=bool(raw.get("require_manual_upload", True)),
            daily_upload_cap=int(raw.get("daily_upload_cap", 5)),
            auto_approve=bool(raw.get("auto_approve", False)),
            auto_generate_images=bool(raw.get("auto_generate_images", False)),
            auto_printify=bool(raw.get("auto_printify", False)),
            printify_publish=bool(raw.get("printify_publish", False)),
            uploads_per_cycle=int(raw.get("uploads_per_cycle", 2)),
            image_provider=str(raw.get("image_provider", "openai")),
            openai_image_model=str(raw.get("openai_image_model", "gpt-image-1")),
            openai_image_size=str(raw.get("openai_image_size", "1024x1024")),
            openai_image_quality=str(raw.get("openai_image_quality", "medium")),
            printify=dict(printify_raw),
        )


class AutopilotRunner:
    """Runs the full swarm on a loop with optional Printify publish path."""

    def __init__(
        self,
        db: StoreDatabase,
        config: AutopilotConfig,
        *,
        tracker: SwarmStateTracker | None = None,
        export_dir: Path | None = None,
        image_client: Any | None = None,
        printify_client: Any | None = None,
    ) -> None:
        self.db = db
        self.config = config
        self.tracker = tracker or SwarmStateTracker()
        self.export_dir = export_dir or Path.cwd() / "etsy_ai_space" / "exports"
        self.image_client = image_client
        self.printify_client = printify_client
        self._niche_index = 0
        self._cycles_today = 0
        self._day_stamp = datetime.now(UTC).date()

    def _next_niche(self) -> str:
        niche = self.config.niches[self._niche_index % len(self.config.niches)]
        self._niche_index += 1
        return niche

    def _check_daily_cap(self) -> bool:
        today = datetime.now(UTC).date()
        if today != self._day_stamp:
            self._day_stamp = today
            self._cycles_today = 0
        if self._cycles_today >= self.config.max_cycles_per_day:
            LOGGER.warning(
                "autopilot: daily cap reached (%d cycles)", self.config.max_cycles_per_day
            )
            return False
        return True

    def _run_auto_approve(self) -> int:
        # Orchestrator often already sets approved_for_export → exported; this
        # catches any leftover pending_review / needs_revision drafts.
        count = approve_ready_drafts(self.db, include_needs_revision=True)
        if count:
            self.tracker.log(f"Auto-approved {count} draft(s)")
        else:
            already = len(self.db.listing_drafts(status="exported")) + len(
                self.db.listing_drafts(status="approved_for_export")
            )
            if already:
                self.tracker.log(
                    f"Auto-approve: nothing pending ({already} draft(s) already export-ready)"
                )
        return count

    def _run_auto_images(self) -> dict[str, Any]:
        from ..agents.openai_image_generator import (
            generate_images_for_pending_drafts,
            resolve_image_provider,
        )

        provider = resolve_image_provider(
            self.config.image_provider,
            demo_mode=self.config.demo,
        )
        self.tracker.log(
            f"Auto-generating up to {self.config.uploads_per_cycle} image(s) via {provider}"
        )
        return generate_images_for_pending_drafts(
            self.db,
            limit=self.config.uploads_per_cycle,
            provider=provider,
            model=self.config.openai_image_model,
            size=self.config.openai_image_size,
            quality=self.config.openai_image_quality,
            images_dir=self.export_dir / "images",
            client=self.image_client,
        )

    def _run_auto_printify(self) -> dict[str, Any]:
        from ..printify.uploader import PrintifyConfig, run_printify_upload

        publish = bool(self.config.printify_publish)
        if publish and self.config.require_manual_upload:
            self.tracker.log(
                "printify_publish=true but require_manual_upload=true; "
                "creating Printify products without Etsy publish",
                level="WARNING",
            )
            publish = False

        printify_cfg = PrintifyConfig.load()
        # Prefer live autopilot flags / embedded printify block over a stale file load
        printify_cfg.require_manual_upload = self.config.require_manual_upload
        printify_cfg.daily_upload_cap = self.config.daily_upload_cap
        if self.config.printify.get("shop_id") not in (None, ""):
            printify_cfg.shop_id = int(self.config.printify["shop_id"])
        elif os.environ.get("PRINTIFY_SHOP_ID"):
            printify_cfg.shop_id = int(os.environ["PRINTIFY_SHOP_ID"])

        if self.printify_client is None and not os.environ.get("PRINTIFY_API_TOKEN"):
            msg = "PRINTIFY_API_TOKEN missing; skipping auto Printify upload"
            self.tracker.log(msg, level="WARNING")
            return {"skipped": True, "reason": "missing_printify_token"}

        self.tracker.log(
            f"Auto Printify upload (limit={self.config.uploads_per_cycle}, publish={publish})"
        )
        return run_printify_upload(
            self.db,
            config=printify_cfg,
            client=self.printify_client,
            limit=self.config.uploads_per_cycle,
            publish=publish,
            force_publish=False,
            dry_run=False,
            tracker=self.tracker,
        )

    async def run_cycle(self) -> dict[str, Any]:
        if not self._check_daily_cap():
            return {"skipped": True, "reason": "daily_cycle_cap"}

        niche = self._next_niche()
        self.tracker.log(f"Autopilot cycle starting for niche: {niche}")
        if self.config.use_claude and not os.environ.get("ANTHROPIC_API_KEY"):
            self.tracker.log(
                "use_claude=true but ANTHROPIC_API_KEY missing; using templates",
                level="WARNING",
            )

        result = await run_orchestrator(
            niche,
            self.db,
            demo=self.config.demo,
            max_results=self.config.max_results_per_scrape,
            concept_count=self.config.concepts_per_cycle,
            export_dir=self.export_dir,
            tracker=self.tracker,
        )
        self._cycles_today += 1

        approved_now = 0
        images: dict[str, Any] = {"generated": 0, "skipped": True}
        printify: dict[str, Any] = {"uploaded": 0, "skipped": True}

        if self.config.auto_approve:
            approved_now = self._run_auto_approve()

        if self.config.auto_generate_images:
            try:
                images = self._run_auto_images()
            except Exception as exc:
                LOGGER.exception("Auto image generation failed")
                self.tracker.log(f"Auto image error: {exc}", level="ERROR")
                images = {"generated": 0, "error": str(exc)}

        if self.config.auto_printify:
            try:
                printify = self._run_auto_printify()
            except Exception as exc:
                LOGGER.exception("Auto Printify upload failed")
                self.tracker.log(f"Auto Printify error: {exc}", level="ERROR")
                printify = {"uploaded": 0, "error": str(exc)}

        pending = len(self.db.listing_drafts(status="pending_review"))
        approved = len(self.db.listing_drafts(status="approved_for_export"))
        next_action = _next_action_message(self.config, printify)

        summary = {
            "niche": niche,
            "cycle": self._cycles_today,
            "concepts": len(result.get("concepts") or []),
            "drafts": len(result.get("drafts") or []),
            "export": result.get("export"),
            "auto_approved": approved_now,
            "images": images,
            "printify": printify,
            "pending_review": pending,
            "approved_for_export": approved,
            "next_action": next_action,
        }
        self.tracker.log(f"Autopilot cycle done: {json.dumps(summary, default=str)}")
        return summary

    async def run_forever(self) -> None:
        mode = "full n8n-style path" if self.config.auto_printify else "research + draft (manual upload gate)"
        self.tracker.log(f"Autopilot started — {mode}")
        while True:
            try:
                await self.run_cycle()
            except Exception as exc:
                LOGGER.exception("Autopilot cycle failed")
                self.tracker.log(f"Autopilot cycle error: {exc}", level="ERROR")
            LOGGER.info(
                "autopilot: sleeping %.0fs until next cycle",
                self.config.cycle_interval_seconds,
            )
            await asyncio.sleep(self.config.cycle_interval_seconds)


def _next_action_message(config: AutopilotConfig, printify: dict[str, Any]) -> str:
    if config.auto_printify and printify.get("skipped"):
        reason = printify.get("reason") or "skipped"
        if reason == "missing_printify_token":
            return "Set PRINTIFY_API_TOKEN (+ PRINTIFY_SHOP_ID), then re-run autopilot or printify-upload"
        return f"Printify skipped ({reason})"
    if config.auto_printify and printify.get("error"):
        return f"Fix Printify error and retry: {printify.get('error')}"
    if config.auto_printify and printify.get("uploaded"):
        if printify.get("published") or config.printify_publish:
            return "Autopilot published via Printify; monitor shop + daily_upload_cap"
        return "Autopilot created Printify products; review/publish in Printify if needed"
    if config.auto_generate_images and not config.auto_printify:
        return "Images attached; run: python3 -m etsy_ai_space printify-upload --dry-run"
    if config.auto_approve and not config.auto_generate_images:
        return "Drafts approved; attach images then printify-upload"
    return (
        "Review exports, then: python3 -m etsy_ai_space approve && "
        "cursor-generate / printify-upload"
    )


def approve_ready_drafts(db: StoreDatabase, *, include_needs_revision: bool = False) -> int:
    """Move drafts awaiting human sign-off to approved_for_export."""
    statuses = ["pending_review"]
    if include_needs_revision:
        statuses.append("needs_revision")
    count = 0
    with db.connection() as conn:
        for status in statuses:
            rows = conn.execute(
                "SELECT id FROM listing_drafts WHERE status = ?", (status,)
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE listing_drafts SET status = ? WHERE id = ?",
                    ("approved_for_export", row["id"]),
                )
                count += 1
    return count


def record_manual_upload(db: StoreDatabase, *, count: int = 1, revenue_usd: float = 0.0) -> None:
    """Track manual uploads and revenue for scaling metrics."""
    tracker = SwarmStateTracker()
    tracker.bump_metric("successful_uploads", count)
    if revenue_usd > 0:
        state = tracker.load()
        metrics = state.setdefault("metrics", {})
        metrics["revenue_usd"] = float(metrics.get("revenue_usd") or 0) + revenue_usd
        tracker.save(state)
    tracker.log(f"Recorded {count} manual upload(s), revenue=${revenue_usd:.2f}")
    tracker.sync_metrics_from_db(db.stats())
