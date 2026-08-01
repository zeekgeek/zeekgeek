"""Command-line entry for the Etsy AI Space swarm."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .agents.researcher.runner import build_scraper, run_researcher
from .agents.ultron.orchestrator import UltronOrchestrator
from .db import StoreDatabase, default_db_path
from .export.bundle import export_pending_drafts
from .pipeline.autopilot import (
    AutopilotConfig,
    AutopilotRunner,
    approve_ready_drafts,
    record_manual_upload,
)
from .pipeline.state_tracker import SwarmStateTracker
from .agents.cursor_image_generator import (
    default_images_dir,
    list_pending_image_jobs,
    save_generated_image,
)
from .pipeline.orchestrator import run_orchestrator
from .scraper.etsy_scraper import scrape_niche_to_db

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Etsy AI Space — safe phased swarm for POD trend research and manual rollout",
    )
    parser.add_argument("--db", type=Path, default=None, help=f"SQLite path (default: {default_db_path()})")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    sub = parser.add_subparsers(dest="command", required=True)

    scrape = sub.add_parser("scrape", help="Phase 1 — scrape and store high-performing listings")
    scrape.add_argument("query", help="Etsy search query, e.g. 'retro cat shirt'")
    scrape.add_argument("--demo", action="store_true", help="Use offline demo data (recommended in cloud CI)")
    scrape.add_argument("--max-results", type=int, default=48)
    scrape.add_argument("--min-score", type=float, default=35.0)
    scrape.add_argument("--headless", action="store_true", default=True)
    scrape.add_argument(
        "--cdp-url",
        default=None,
        help="Attach to BrowserClaw via CDP (http or WebSocket debugger URL)",
    )
    scrape.add_argument("--reuse-tab", action="store_true", help="Reuse active BrowserClaw tab")

    browserclaw = sub.add_parser(
        "browserclaw-scrape",
        help="Scrape autopilot niches via active BrowserClaw CDP session",
    )
    browserclaw.add_argument("query", nargs="?", default=None, help="Optional single niche")
    browserclaw.add_argument("--cdp-url", default=None)
    browserclaw.add_argument("--config", type=Path, default=None)
    browserclaw.add_argument("--all-niches", action="store_true")
    browserclaw.add_argument("--max-results", type=int, default=24)
    browserclaw.add_argument("--min-score", type=float, default=35.0)
    browserclaw.add_argument("--reuse-tab", action="store_true")
    browserclaw.add_argument("--db", type=Path, default=None)

    pipeline = sub.add_parser("pipeline", help="Run phases 1–4 and export a manual upload bundle")
    pipeline.add_argument("query", help="Seed Etsy search query / niche")
    pipeline.add_argument("--niche", default=None, help="Creative niche override")
    pipeline.add_argument("--demo", action="store_true", help="Use demo scraper instead of Playwright")
    pipeline.add_argument("--export-dir", type=Path, default=None)
    pipeline.add_argument("--max-results", type=int, default=48)

    orchestrate = sub.add_parser(
        "orchestrate",
        help="Scrape → manager (5 concepts) → worker agents → export",
    )
    orchestrate.add_argument("niche", help="Niche query, e.g. 'retro cat shirt'")
    orchestrate.add_argument("--demo", action="store_true")
    orchestrate.add_argument("--concepts", type=int, default=5)
    orchestrate.add_argument("--skip-scrape", action="store_true")
    orchestrate.add_argument("--export-dir", type=Path, default=None)
    orchestrate.add_argument("--max-results", type=int, default=48)

    export = sub.add_parser("export", help="Phase 4 — export pending listing drafts to JSON/CSV")
    export.add_argument("--export-dir", type=Path, default=None)

    stats = sub.add_parser("stats", help="Show SQLite store statistics")

    top = sub.add_parser("top", help="Print top stored listings by performance score")
    top.add_argument("--limit", type=int, default=10)

    dashboard = sub.add_parser("dashboard", help="Launch Streamlit swarm status dashboard")
    dashboard.add_argument("--port", type=int, default=8501)
    dashboard.add_argument("--refresh", type=int, default=3, help="Auto-refresh interval in seconds")

    cursor_generate = sub.add_parser(
        "cursor-generate",
        help="List or attach Cursor-agent-generated images for listing drafts",
    )
    cursor_generate.add_argument(
        "--list",
        action="store_true",
        help="List pending image generation jobs (drafts with image_prompt but no image_path)",
    )
    cursor_generate.add_argument(
        "--all",
        action="store_true",
        help="Agent-friendly alias for --list: emit all pending jobs as JSON",
    )
    cursor_generate.add_argument(
        "--attach",
        nargs=2,
        metavar=("DRAFT_ID", "IMAGE_FILE"),
        help="Attach a generated image file to a listing draft",
    )
    cursor_generate.add_argument(
        "--status",
        default=None,
        help="Only consider drafts with this status (default: any status)",
    )
    cursor_generate.add_argument(
        "--include-needs-revision",
        action="store_true",
        help="Also include drafts that need revision",
    )
    cursor_generate.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing image for the same draft",
    )
    cursor_generate.add_argument(
        "--images-dir",
        type=Path,
        default=None,
        help=f"Directory to store generated images (default: {default_images_dir()})",
    )

    autopilot = sub.add_parser("autopilot", help="Autonomous loop: scrape → concepts → export")
    autopilot.add_argument("--config", type=Path, default=None, help="Path to autopilot.yaml")
    autopilot.add_argument("--once", action="store_true", help="Run one cycle and exit")
    autopilot.add_argument("--demo", action="store_true", help="Override config demo=true")

    approve = sub.add_parser("approve", help="Approve drafts for manual Etsy upload")
    approve.add_argument("--include-needs-revision", action="store_true")

    record = sub.add_parser("record-upload", help="Log manual uploads and revenue")
    record.add_argument("--count", type=int, default=1)
    record.add_argument("--revenue", type=float, default=0.0)

    queue = sub.add_parser("queue", help="Show listing drafts by status")

    return parser


async def cmd_scrape(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    if args.demo:
        scraper = build_scraper(demo=True, headless=args.headless)
        result = await run_researcher(
            args.query,
            db,
            backend=scraper,
            max_results=args.max_results,
            min_score=args.min_score,
        )
    else:
        result = await scrape_niche_to_db(
            args.query,
            db,
            demo=False,
            max_results=args.max_results,
            min_score=args.min_score,
            headless=args.headless,
            cdp_url=args.cdp_url,
            reuse_browser_tab=getattr(args, "reuse_tab", False),
        )
    print(json.dumps(result, indent=2))
    return 0


async def cmd_browserclaw_scrape(args: argparse.Namespace) -> int:
    from .scraper.browserclaw_scraper import _cli as browserclaw_cli

    return await browserclaw_cli(args)


async def cmd_orchestrate(args: argparse.Namespace) -> int:
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


async def cmd_pipeline(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    orchestrator = UltronOrchestrator(
        db,
        demo=args.demo,
        export_dir=str(args.export_dir) if args.export_dir else None,
    )
    result = await orchestrator.run_pipeline(
        args.query,
        niche=args.niche,
        max_results=args.max_results,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    out_dir = args.export_dir or Path.cwd() / "etsy_ai_space" / "exports"
    paths = export_pending_drafts(db, out_dir)
    print(json.dumps(paths, indent=2))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    print(json.dumps(db.stats(), indent=2))
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    rows = db.top_listings(limit=args.limit)
    print(json.dumps(rows, indent=2))
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    payload = {
        "approved_for_export": db.listing_drafts(status="approved_for_export"),
        "pending_review": db.listing_drafts(status="pending_review"),
        "needs_revision": db.listing_drafts(status="needs_revision"),
        "exported": db.listing_drafts(status="exported"),
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    count = approve_ready_drafts(db, include_needs_revision=args.include_needs_revision)
    approved = db.listing_drafts(status="approved_for_export")
    print(json.dumps({"approved_now": count, "total_approved": len(approved)}, indent=2))
    return 0


def cmd_record_upload(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    record_manual_upload(db, count=args.count, revenue_usd=args.revenue)
    tracker = SwarmStateTracker()
    print(json.dumps(tracker.load().get("metrics", {}), indent=2))
    return 0


async def cmd_autopilot(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    config = AutopilotConfig.load(args.config)
    if args.demo:
        config.demo = True
    runner = AutopilotRunner(db, config)
    if args.once:
        result = await runner.run_cycle()
        print(json.dumps(result, indent=2))
        return 0
    await runner.run_forever()
    return 0


def cmd_cursor_generate(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    if args.list or args.all:
        jobs = list_pending_image_jobs(
            db,
            status=args.status,
            include_needs_revision=args.include_needs_revision,
        )
        print(json.dumps(jobs, indent=2))
        return 0
    if args.attach:
        draft_id = int(args.attach[0])
        image_file = Path(args.attach[1])
        dest = save_generated_image(
            draft_id,
            image_file,
            db,
            images_dir=args.images_dir,
            force=args.force,
        )
        print(json.dumps({"draft_id": draft_id, "image_path": str(dest)}, indent=2))
        return 0
    print("Use --list, --all, or --attach <draft-id> <image-file>", file=sys.stderr)
    return 1


def cmd_dashboard(args: argparse.Namespace) -> int:
    import subprocess
    import sys

    app_path = Path(__file__).resolve().parent.parent / "dashboard" / "streamlit_main.py"
    env = {"ETSY_DASHBOARD_REFRESH": str(args.refresh)}
    import os

    merged = os.environ.copy()
    merged.update(env)
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(args.port),
        "--server.headless",
        "true",
    ]
    raise SystemExit(subprocess.call(cmd, env=merged))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))

    if args.command == "scrape":
        raise SystemExit(asyncio.run(cmd_scrape(args)))
    if args.command == "browserclaw-scrape":
        raise SystemExit(asyncio.run(cmd_browserclaw_scrape(args)))
    if args.command == "orchestrate":
        raise SystemExit(asyncio.run(cmd_orchestrate(args)))
    if args.command == "pipeline":
        raise SystemExit(asyncio.run(cmd_pipeline(args)))
    if args.command == "export":
        raise SystemExit(cmd_export(args))
    if args.command == "stats":
        raise SystemExit(cmd_stats(args))
    if args.command == "top":
        raise SystemExit(cmd_top(args))
    if args.command == "cursor-generate":
        raise SystemExit(cmd_cursor_generate(args))
    if args.command == "dashboard":
        raise SystemExit(cmd_dashboard(args))
    if args.command == "autopilot":
        raise SystemExit(asyncio.run(cmd_autopilot(args)))
    if args.command == "approve":
        raise SystemExit(cmd_approve(args))
    if args.command == "record-upload":
        raise SystemExit(cmd_record_upload(args))
    if args.command == "queue":
        raise SystemExit(cmd_queue(args))
    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
