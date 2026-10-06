-- 0001_initial.sql  Canonical schema, DuckDB dialect (also valid on MotherDuck).
-- Ids are content hashes so re-runs are idempotent (no sequences, no auto-increment).

CREATE TABLE IF NOT EXISTS outlet (
    outlet_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    domain      TEXT NOT NULL,
    discovery   TEXT NOT NULL,          -- rss | sitemap
    feed_url    TEXT NOT NULL,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS article (
    article_id          TEXT PRIMARY KEY,          -- md5(canonical url)
    outlet_id           TEXT NOT NULL REFERENCES outlet(outlet_id),
    url                 TEXT NOT NULL UNIQUE,
    title               TEXT,
    published_at        TIMESTAMP,
    category            TEXT,
    language            TEXT,
    word_count          INTEGER,
    word_count_source   TEXT NOT NULL,             -- native | derived
    metric_completeness TEXT NOT NULL,             -- full | volume_only
    source_type         TEXT NOT NULL,             -- rss | sitemap | gdelt | ccnews
    extraction_method   TEXT,
    extraction_confidence DOUBLE,
    first_seen_at       TIMESTAMP NOT NULL,
    last_seen_at        TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS author (
    author_id      TEXT PRIMARY KEY,             -- md5(outlet_id || '|' || normalized_name)
    outlet_id      TEXT NOT NULL REFERENCES outlet(outlet_id),
    canonical_name TEXT NOT NULL,
    first_seen_at  TIMESTAMP NOT NULL,
    last_seen_at   TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS article_author (
    article_id   TEXT NOT NULL REFERENCES article(article_id),
    author_id    TEXT NOT NULL REFERENCES author(author_id),
    author_order INTEGER NOT NULL,
    PRIMARY KEY (article_id, author_id)
);

CREATE TABLE IF NOT EXISTS ingest_run (
    run_id       TEXT PRIMARY KEY,
    started_at   TIMESTAMP NOT NULL,
    finished_at  TIMESTAMP,
    rows_in      INTEGER,
    rows_flagged INTEGER,
    status       TEXT NOT NULL                   -- running | ok | error
);

CREATE TABLE IF NOT EXISTS dq_result (
    run_id     TEXT NOT NULL REFERENCES ingest_run(run_id),
    check_name TEXT NOT NULL,
    passed     BOOLEAN NOT NULL,
    detail     TEXT
);
