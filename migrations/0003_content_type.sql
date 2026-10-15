-- 0003_content_type.sql  Content-genre classification on the article table.
-- Decision 2026-10-14 (word-count divergence investigation): list/deal/guide
-- pages are a distinct genre that pollutes length averages and that GDELT's
-- archive `wc:` collapses to a quantized floor (multiples of 25). Genre is
-- classified from per-outlet URL patterns (sources.yaml `list_url_pattern`),
-- not a global regex (precision 0.98 for LA Times /list/, recall 0.00 for
-- outlets whose CMS uses generic paths). Unvalidated outlets stay 'article'.

ALTER TABLE article ADD COLUMN IF NOT EXISTS content_type TEXT;

-- Snapshot backfill mirroring the current sources.yaml patterns. The forward
-- ETL classifies at normalize time; this brings archive rows (loaded before
-- the column existed, and via direct SQL in sync_backfill) up to the same
-- state. Re-running is idempotent; explicit values win over the default.
UPDATE article SET content_type = 'article' WHERE content_type IS NULL;
UPDATE article SET content_type = 'list'
WHERE outlet_id = 'latimes'
  AND regexp_matches(url, '/(list|listicle)s?/');
