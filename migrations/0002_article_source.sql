-- 0002_article_source.sql   Per-pipeline provenance for the conformed article table.
-- Decision 2026-10-09 (JMD-79 Build Plan v2, M6.5): one conformed `article` keyed on
-- article_id, with provenance in a companion table rather than columns on the fact row.
-- One row per (article, observing pipeline): forward RSS/sitemap, GDELT backfill, etc.
-- raw_word_count keeps each pipeline's own measurement (trafilatura tokens vs GDELT wc:).

CREATE TABLE IF NOT EXISTS article_source (
    article_id            TEXT NOT NULL REFERENCES article(article_id),
    source_type           TEXT NOT NULL,          -- rss | sitemap | gdelt | ccnews
    first_seen_at         TIMESTAMP NOT NULL,
    extraction_method     TEXT,
    extraction_confidence DOUBLE,
    raw_word_count        INTEGER,
    PRIMARY KEY (article_id, source_type)
);
