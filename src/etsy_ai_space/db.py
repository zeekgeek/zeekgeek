"""SQLite persistence for scrape runs, listings, and export drafts."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import CreativeBrief, ListingDraft, ProductConcept, ScrapeRun, ScrapedListing, iso_time, utc_now

SCHEMA_PATH = Path(__file__).parent / "database" / "schema.sql"


def default_db_path() -> Path:
    return Path.cwd() / "etsy_ai_space" / "data" / "store.db"


def load_schema_sql() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


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
            conn.executescript(load_schema_sql())
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        listing_cols = {row[1] for row in conn.execute("PRAGMA table_info(listing_drafts)")}
        if listing_cols and "concept_id" not in listing_cols:
            conn.execute("ALTER TABLE listing_drafts ADD COLUMN concept_id INTEGER REFERENCES product_concepts(id)")

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
                json.dumps(item.tags),
                item.price_amount,
                item.price_currency,
                item.review_count,
                item.rating,
                item.favorites,
                item.shop_name,
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
                    scrape_run_id, etsy_listing_id, title, tags_json, price_amount,
                    price_currency, review_count, rating, favorites, shop_name, url,
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

    def save_concept(self, concept: ProductConcept) -> ProductConcept:
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO product_concepts (
                    concept_name, hook, angle, trend_summary,
                    reference_listing_ids_json, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    concept.concept_name,
                    concept.hook,
                    concept.angle,
                    concept.trend_summary,
                    json.dumps(concept.reference_listing_ids),
                    iso_time(concept.created_at),
                    concept.status,
                ),
            )
            concept.id = int(cur.lastrowid)
        return concept

    def product_concepts(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM product_concepts
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["reference_listing_ids"] = json.loads(item.pop("reference_listing_ids_json"))
            result.append(item)
        return result

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
                    concept_id, brief_id, title, description, tags_json, price, image_prompt,
                    image_path, taxonomy_hint, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.concept_id,
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
            concept_count = conn.execute("SELECT COUNT(*) FROM product_concepts").fetchone()[0]
            avg_score = conn.execute(
                "SELECT AVG(performance_score) FROM listings WHERE performance_score IS NOT NULL"
            ).fetchone()[0]
        return {
            "db_path": str(self.path),
            "listings": listing_count,
            "scrape_runs": run_count,
            "product_concepts": concept_count,
            "listing_drafts": draft_count,
            "avg_performance_score": round(avg_score, 2) if avg_score is not None else None,
        }

    @staticmethod
    def _listing_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["tags"] = json.loads(item.pop("tags_json"))
        return item
