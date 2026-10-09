"""dbt-style modeling: conform and build mart views.

The raw tables (`article`, `author`, `article_author`, `outlet`) are the
staging layer, loaded by the ETL. `build_marts` applies one conforming step
(normalizing any category values still in raw form) and then creates the
aggregate mart views the dashboard and chatbot read from.
"""

from __future__ import annotations

from newsstats.category import normalize_category

_MARTS: list[tuple[str, str]] = [
    (
        "dim_outlet",
        """
        CREATE OR REPLACE VIEW dim_outlet AS
        SELECT o.outlet_id, o.name, o.domain,
               count(a.article_id) AS article_count,
               round(avg(a.word_count), 1) AS avg_word_count,
               count(a.article_id) FILTER (WHERE a.word_count_source = 'derived')
                   AS article_count_derived,
               count(a.article_id) FILTER (WHERE a.word_count_source = 'archive')
                   AS article_count_archive,
               round(avg(a.word_count) FILTER (WHERE a.word_count_source = 'derived'), 1)
                   AS avg_word_count_derived,
               round(avg(a.word_count) FILTER (WHERE a.word_count_source = 'archive'), 1)
                   AS avg_word_count_archive
        FROM outlet o
        LEFT JOIN article a ON a.outlet_id = o.outlet_id
        GROUP BY o.outlet_id, o.name, o.domain
        """,
    ),
    (
        "dim_author",
        """
        CREATE OR REPLACE VIEW dim_author AS
        SELECT au.author_id, au.outlet_id, au.canonical_name,
               count(aa.article_id) AS article_count,
               round(avg(ar.word_count), 1) AS avg_word_count,
               min(ar.first_seen_at) AS first_seen_at,
               max(ar.last_seen_at) AS last_seen_at
        FROM author au
        LEFT JOIN article_author aa ON aa.author_id = au.author_id
        LEFT JOIN article ar ON ar.article_id = aa.article_id
        GROUP BY au.author_id, au.outlet_id, au.canonical_name
        """,
    ),
    (
        "agg_outlet_daily",
        """
        CREATE OR REPLACE VIEW agg_outlet_daily AS
        SELECT outlet_id,
               CAST(published_at AS DATE) AS day,
               count(*) AS article_count,
               round(avg(word_count), 1) AS avg_word_count,
               sum(word_count) AS total_words,
               count(*) FILTER (WHERE word_count_source = 'derived')
                   AS article_count_derived,
               count(*) FILTER (WHERE word_count_source = 'archive')
                   AS article_count_archive,
               round(avg(word_count) FILTER (WHERE word_count_source = 'derived'), 1)
                   AS avg_word_count_derived,
               round(avg(word_count) FILTER (WHERE word_count_source = 'archive'), 1)
                   AS avg_word_count_archive,
               sum(word_count) FILTER (WHERE word_count_source = 'derived')
                   AS total_words_derived,
               sum(word_count) FILTER (WHERE word_count_source = 'archive')
                   AS total_words_archive
        FROM article
        WHERE published_at IS NOT NULL AND metric_completeness = 'full'
        GROUP BY outlet_id, CAST(published_at AS DATE)
        """,
    ),
    (
        "agg_author_week",
        """
        CREATE OR REPLACE VIEW agg_author_week AS
        SELECT au.canonical_name, au.outlet_id,
               date_trunc('week', ar.published_at) AS week,
               count(*) AS article_count,
               round(avg(ar.word_count), 1) AS avg_word_count,
               sum(ar.word_count) AS total_words
        FROM article ar
        JOIN article_author aa ON aa.article_id = ar.article_id
        JOIN author au ON au.author_id = aa.author_id
        WHERE ar.published_at IS NOT NULL AND ar.metric_completeness = 'full'
        GROUP BY au.canonical_name, au.outlet_id, date_trunc('week', ar.published_at)
        """,
    ),
    (
        "agg_author_month",
        """
        CREATE OR REPLACE VIEW agg_author_month AS
        SELECT au.canonical_name, au.outlet_id,
               date_trunc('month', ar.published_at) AS month,
               count(*) AS article_count,
               round(avg(ar.word_count), 1) AS avg_word_count,
               sum(ar.word_count) AS total_words
        FROM article ar
        JOIN article_author aa ON aa.article_id = ar.article_id
        JOIN author au ON au.author_id = aa.author_id
        WHERE ar.published_at IS NOT NULL AND ar.metric_completeness = 'full'
        GROUP BY au.canonical_name, au.outlet_id, date_trunc('month', ar.published_at)
        """,
    ),
    (
        "agg_author_rolling",
        """
        CREATE OR REPLACE VIEW agg_author_rolling AS
        SELECT au.canonical_name, au.outlet_id,
               sum(CASE WHEN ar.published_at >= current_date - INTERVAL 7 DAY
                        THEN 1 ELSE 0 END) AS articles_7d,
               sum(CASE WHEN ar.published_at >= current_date - INTERVAL 30 DAY
                        THEN 1 ELSE 0 END) AS articles_30d,
               coalesce(sum(CASE WHEN ar.published_at >= current_date - INTERVAL 7 DAY
                        THEN ar.word_count END), 0) AS words_7d,
               coalesce(sum(CASE WHEN ar.published_at >= current_date - INTERVAL 30 DAY
                        THEN ar.word_count END), 0) AS words_30d
        FROM article ar
        JOIN article_author aa ON aa.article_id = ar.article_id
        JOIN author au ON au.author_id = aa.author_id
        WHERE ar.metric_completeness = 'full'
        GROUP BY au.canonical_name, au.outlet_id
        """,
    ),
]


def _backfill_categories(conn) -> int:
    # Forward rows only: the archive (GDELT) side carries no publisher section, so
    # conforming it is a no-op and scanning 3M rows every build is wasted compute.
    cats = conn.execute(
        "SELECT DISTINCT category FROM article "
        "WHERE category IS NOT NULL AND word_count_source = 'derived'"
    ).fetchall()
    changed = 0
    for (cat,) in cats:
        norm = normalize_category(cat)
        if norm != cat:
            conn.execute("UPDATE article SET category=? WHERE category=?", [norm, cat])
            changed += 1
    return changed


def build_marts(conn) -> int:
    _backfill_categories(conn)
    for _, sql in _MARTS:
        conn.execute(sql)
    return len(_MARTS)
