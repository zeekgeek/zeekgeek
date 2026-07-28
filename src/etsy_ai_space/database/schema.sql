-- Etsy AI Space — SQLite schema for trend research and product pipeline

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
    scrape_run_id INTEGER NOT NULL,
    etsy_listing_id TEXT,
    title TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    price_amount REAL,
    price_currency TEXT NOT NULL DEFAULT 'USD',
    review_count INTEGER,
    rating REAL,
    favorites INTEGER,
    shop_name TEXT,
    url TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    performance_score REAL,
    FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_listings_score ON listings(performance_score DESC);
CREATE INDEX IF NOT EXISTS idx_listings_scraped ON listings(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_listings_etsy_id ON listings(etsy_listing_id);

CREATE TABLE IF NOT EXISTS product_concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_name TEXT NOT NULL,
    hook TEXT NOT NULL,
    angle TEXT NOT NULL,
    trend_summary TEXT NOT NULL,
    reference_listing_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
);

CREATE TABLE IF NOT EXISTS creative_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_summary TEXT NOT NULL,
    brief_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
);

CREATE TABLE IF NOT EXISTS listing_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id INTEGER REFERENCES product_concepts(id),
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
    FOREIGN KEY (concept_id) REFERENCES product_concepts(id),
    FOREIGN KEY (brief_id) REFERENCES creative_briefs(id)
);
