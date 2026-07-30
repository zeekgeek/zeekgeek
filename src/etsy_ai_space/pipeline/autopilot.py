"""Autonomous pipeline runner — scrape, concept, export on a schedule."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..db import StoreDatabase, default_db_path
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
    scrape_mode: str = "demo"
    cdp_url: str | None = None
    reuse_browser_tab: bool = False
    cdp_auto_discover: bool = True
    cdp_fallback_demo: bool = True
    use_claude: bool = False
    require_manual_upload: bool = True
    daily_upload_cap: int = 5

    @classmethod
    def load(cls, path: Path | None = None) -> AutopilotConfig:
        config_path = path or DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return cls(niches=["retro cat shirt"], demo=True)
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        niches = raw.get("niches") or ["retro cat shirt"]
        demo = bool(raw.get("demo", True))
        scrape_mode = str(raw.get("scrape_mode") or ("demo" if demo else "browserclaw"))
        return cls(
            niches=[str(n) for n in niches],
            cycle_interval_seconds=float(raw.get("cycle_interval_seconds", 21600)),
            max_cycles_per_day=int(raw.get("max_cycles_per_day", 4)),
            concepts_per_cycle=int(raw.get("concepts_per_cycle", 5)),
            max_results_per_scrape=int(raw.get("max_results_per_scrape", 24)),
            demo=demo,
            scrape_mode=scrape_mode,
            cdp_url=(str(raw["cdp_url"]).strip() if raw.get("cdp_url") else None),
            reuse_browser_tab=bool(raw.get("reuse_browser_tab", False)),
            cdp_auto_discover=bool(raw.get("cdp_auto_discover", True)),
            cdp_fallback_demo=bool(raw.get("cdp_fallback_demo", True)),
            use_claude=bool(raw.get("use_claude", False)),
            require_manual_upload=bool(raw.get("require_manual_upload", True)),
            daily_upload_cap=int(raw.get("daily_upload_cap", 5)),
        )


class AutopilotRunner:
    """Runs the full swarm on a loop with safety caps and state tracking."""

    def __init__(
        self,
        db: StoreDatabase,
        config: AutopilotConfig,
        *,
        tracker: SwarmStateTracker | None = None,
        export_dir: Path | None = None,
    ) -> None:
        self.db = db
        self.config = config
        self.tracker = tracker or SwarmStateTracker()
        self.export_dir = export_dir or Path.cwd() / "etsy_ai_space" / "exports"
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

    async def run_cycle(self) -> dict[str, Any]:
        if not self._check_daily_cap():
            return {"skipped": True, "reason": "daily_cycle_cap"}

        niche = self._next_niche()
        self.tracker.log(f"Autopilot cycle starting for niche: {niche}")
        if self.config.use_claude and not os.environ.get("ANTHROPIC_API_KEY"):
            self.tracker.log("use_claude=true but ANTHROPIC_API_KEY missing; using templates", level="WARNING")

        result = await run_orchestrator(
            niche,
            self.db,
            demo=self.config.demo,
            scrape_mode=self.config.scrape_mode,
            cdp_url=self.config.cdp_url,
            reuse_browser_tab=self.config.reuse_browser_tab,
            cdp_auto_discover=self.config.cdp_auto_discover,
            cdp_fallback_demo=self.config.cdp_fallback_demo,
            max_results=self.config.max_results_per_scrape,
            concept_count=self.config.concepts_per_cycle,
            export_dir=self.export_dir,
            tracker=self.tracker,
            require_manual_upload=self.config.require_manual_upload,
        )
        self._cycles_today += 1

        pending = len(self.db.listing_drafts(status="pending_review"))
        approved = len(self.db.listing_drafts(status="approved_for_export"))
        summary = {
            "niche": niche,
            "cycle": self._cycles_today,
            "scrape_settings": result.get("scrape_settings"),
            "concepts": len(result.get("concepts") or []),
            "drafts": len(result.get("drafts") or []),
            "export": result.get("export"),
            "pending_review": pending,
            "approved_for_export": approved,
            "next_action": (
                "Review drafts, then run: python3 -m etsy_ai_space approve && "
                "python3 -m etsy_ai_space export"
                if self.config.require_manual_upload
                else "Review the exported bundle before uploading manually"
            ),
        }
        self.tracker.log(f"Autopilot cycle done: {json.dumps(summary, default=str)}")
        return summary

    async def run_forever(self) -> None:
        self.tracker.log(
            "Autopilot started — scrape → concepts → review queue "
            f"(scrape_mode={self.config.scrape_mode}, demo={self.config.demo})"
        )
        while True:
            try:
                await self.run_cycle()
            except Exception as exc:
                LOGGER.exception("Autopilot cycle failed")
                self.tracker.log(f"Autopilot cycle error: {exc}", level="ERROR")
            LOGGER.info("autopilot: sleeping %.0fs until next cycle", self.config.cycle_interval_seconds)
            await asyncio.sleep(self.config.cycle_interval_seconds)


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
