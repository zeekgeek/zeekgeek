"""SQLite persistence for scrape runs, listings, and export drafts."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import CreativeBrief, ListingDraft, ScrapeRun, ScrapedListing, iso_time, utc_now


SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    listing_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_run_id INTEGER NOT NULL REFERENCES scrape_runs(id),
    etsy_listing_id TEXT,
    title TEXT NOT NULL,
    price_amount REAL,
    price_currency TEXT NOT NULL DEFAULT 'USD',
    tags_json TEXT NOT NULL DEFAULT '[]',
    shop_name TEXT,
    review_count INTEGER,
    rating REAL,
    favorites INTEGER,
    url TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    performance_score REAL,
    FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_listings_score ON listings(performance_score DESC);
CREATE INDEX IF NOT EXISTS idx_listings_scraped ON listings(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_listings_etsy_id ON listings(etsy_listing_id);

CREATE TABLE IF NOT EXISTS creative_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_summary TEXT NOT NULL,
    brief_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
);

CREATE TABLE IF NOT EXISTS listing_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_id INTEGER REFERENCES creative_briefs(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    price REAL NOT NULL,
    image_prompt TEXT NOT NULL,
    image_path TEXT,
    taxonomy_hint TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    export_json TEXT,
    FOREIGN KEY (brief_id) REFERENCES creative_briefs(id)
);
"""


def default_db_path() -> Path:
    return Path.cwd() / "etsy_ai_space" / "data" / "store.db"


class StoreDatabase:
    """Thread-local SQLite access for the Etsy AI swarm."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    def start_scrape_run(self, query: str, source: str) -> ScrapeRun:
        run = ScrapeRun(query=query, source=source)
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO scrape_runs (query, source, started_at, status)
                VALUES (?, ?, ?, ?)
                """,
                (run.query, run.source, iso_time(run.started_at), run.status),
            )
            run.id = int(cur.lastrowid)
        return run

    def finish_scrape_run(self, run_id: int, *, listing_count: int, status: str = "completed") -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE scrape_runs
                SET finished_at = ?, listing_count = ?, status = ?
                WHERE id = ?
                """,
                (iso_time(), listing_count, status, run_id),
            )

    def insert_listings(self, run_id: int, listings: list[ScrapedListing]) -> int:
        rows = [
            (
                run_id,
                item.etsy_listing_id,
                item.title,
                item.price_amount,
                item.price_currency,
                json.dumps(item.tags),
                item.shop_name,
                item.review_count,
                item.rating,
                item.favorites,
                item.url,
                iso_time(item.scraped_at),
                item.performance_score,
            )
            for item in listings
        ]
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO listings (
                    scrape_run_id, etsy_listing_id, title, price_amount, price_currency,
                    tags_json, shop_name, review_count, rating, favorites, url,
                    scraped_at, performance_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def top_listings(self, *, limit: int = 25, min_score: float | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT * FROM listings
            WHERE performance_score IS NOT NULL
        """
        params: list[Any] = []
        if min_score is not None:
            query += " AND performance_score >= ?"
            params.append(min_score)
        query += " ORDER BY performance_score DESC, scraped_at DESC LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._listing_row_to_dict(row) for row in rows]

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scrape_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_brief(self, brief: CreativeBrief) -> CreativeBrief:
        payload = json.dumps(brief.to_dict())
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO creative_briefs (trend_summary, brief_json, created_at, status)
                VALUES (?, ?, ?, ?)
                """,
                (brief.trend_summary, payload, iso_time(brief.created_at), brief.status),
            )
            brief.id = int(cur.lastrowid)
        return brief

    def save_listing_draft(self, draft: ListingDraft) -> ListingDraft:
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO listing_drafts (
                    brief_id, title, description, tags_json, price, image_prompt,
                    image_path, taxonomy_hint, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.brief_id,
                    draft.title,
                    draft.description,
                    json.dumps(draft.tags),
                    draft.price,
                    draft.image_prompt,
                    draft.image_path,
                    draft.taxonomy_hint,
                    iso_time(draft.created_at),
                    draft.status,
                ),
            )
            draft.id = int(cur.lastrowid)
        return draft

    def listing_drafts(self, *, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM listing_drafts"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item.pop("tags_json"))
            result.append(item)
        return result

    def stats(self) -> dict[str, Any]:
        with self.connection() as conn:
            listing_count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            run_count = conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0]
            draft_count = conn.execute("SELECT COUNT(*) FROM listing_drafts").fetchone()[0]
            avg_score = conn.execute(
                "SELECT AVG(performance_score) FROM listings WHERE performance_score IS NOT NULL"
            ).fetchone()[0]
        return {
            "db_path": str(self.path),
            "listings": listing_count,
            "scrape_runs": run_count,
            "listing_drafts": draft_count,
            "avg_performance_score": round(avg_score, 2) if avg_score is not None else None,
        }

    @staticmethod
    def _listing_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["tags"] = json.loads(item.pop("tags_json"))
        return item
