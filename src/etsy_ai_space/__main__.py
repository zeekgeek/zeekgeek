"""Command-line entry for the Etsy AI Space swarm."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from .agents.researcher.runner import build_scraper, run_researcher
from .agents.ultron.orchestrator import UltronOrchestrator
from .db import StoreDatabase, default_db_path
from .export.bundle import export_pending_drafts

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

    pipeline = sub.add_parser("pipeline", help="Run phases 1–4 and export a manual upload bundle")
    pipeline.add_argument("query", help="Seed Etsy search query / niche")
    pipeline.add_argument("--niche", default=None, help="Creative niche override")
    pipeline.add_argument("--demo", action="store_true", help="Use demo scraper instead of Playwright")
    pipeline.add_argument("--export-dir", type=Path, default=None)
    pipeline.add_argument("--max-results", type=int, default=48)

    export = sub.add_parser("export", help="Phase 4 — export pending listing drafts to JSON/CSV")
    export.add_argument("--export-dir", type=Path, default=None)

    stats = sub.add_parser("stats", help="Show SQLite store statistics")

    top = sub.add_parser("top", help="Print top stored listings by performance score")
    top.add_argument("--limit", type=int, default=10)

    return parser


async def cmd_scrape(args: argparse.Namespace) -> int:
    db = StoreDatabase(args.db)
    scraper = build_scraper(demo=args.demo, headless=args.headless)
    result = await run_researcher(
        args.query,
        db,
        backend=scraper,
        max_results=args.max_results,
        min_score=args.min_score,
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


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))

    if args.command == "scrape":
        raise SystemExit(asyncio.run(cmd_scrape(args)))
    if args.command == "pipeline":
        raise SystemExit(asyncio.run(cmd_pipeline(args)))
    if args.command == "export":
        raise SystemExit(cmd_export(args))
    if args.command == "stats":
        raise SystemExit(cmd_stats(args))
    if args.command == "top":
        raise SystemExit(cmd_top(args))
    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
