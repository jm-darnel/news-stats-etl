-- 0004_live_posts_and_pseudo_authors.sql  Two-grade fix for author-metric outliers.
-- Decision 2026-10-14 (agg_author_month investigation): the top author-months are
-- NOT row duplicates (677 articles = 677 distinct URLs). They are two structural
-- artifacts, fixed by classification rather than deletion:
--
-- 1. Live-news posts. CNN/Fox rolling live pages expose one child URL per post
--    (/live-news/<page>/h_<hash>); GDELT indexes every post with the whole team
--    byline (avg 4.2 credited authors) and a page-level wc: (double counting).
--    -> content_type='live_post'; excluded from author marts and length metrics,
--    still counted as volume.
-- 2. Desk pseudo-bylines leaking into `author` from the GDELT side
--    ("US NEWS REPORTER", "DAILY MAIL REPORTER", "CNN Business", ...).
--    -> author.is_pseudo flag (additive: the row and its evidence stay queryable,
--    marts filter it out). Matches author_resolution.is_pseudo after the
--    _DESK_ROLE extension.

-- live-news posts on the two outlets whose CMSes use the path (validated: the
-- pattern catches 15,727 documents, none on other outlets).
UPDATE article SET content_type = 'live_post'
WHERE content_type = 'article'
  AND outlet_id IN ('cnn', 'fox')
  AND regexp_matches(url, '/live-news/');

ALTER TABLE author ADD COLUMN IF NOT EXISTS is_pseudo BOOLEAN;

-- Pure desk bylines: the only words before the role are seniority/topic descriptors
-- ("US NEWS REPORTER", "ASSOCIATE SHOWBUSINESS EDITOR"). Real people with role
-- descriptors ("MARK NICOL DIPLOMACY EDITOR") are NOT flagged: author_resolution
-- strips the role tail and keeps the person at ingest; the compound-name rows are
-- re-evaluated by that same rule outside this migration.
UPDATE author SET is_pseudo = TRUE
WHERE regexp_matches(lower(canonical_name),
    '^(us|usa|senior|assistant|associate|chief|deputy|executive|managing|foreign|political'
    '|diplomacy|diplomatic|science|lifestyle|money|showbusiness|showbiz|sport|sports|city'
    '|health|crime|media|tech|technology|business|football|influencer|news|congressional'
    '|\s)*\s*(reporter|editor|columnist|correspondent|critic|journalist|writer|reviewer'
    '|photographer)s?$')
   OR regexp_matches(lower(canonical_name),
    '^(press association|mail on sunday|daily mail|associated press|reuters|cnn|bbc'
    '|fox news|the sun|the guardian|nbc news|cbs news|new york post|the intercept)\b.*'
    '\s(reporter|editor|columnist|correspondent|critic|journalist|writer|reviewer'
    '|photographer)s?$')
   OR lower(canonical_name) IN ('cnn business', 'the intercept briefing', 'associated');

UPDATE author SET is_pseudo = FALSE WHERE is_pseudo IS NULL;