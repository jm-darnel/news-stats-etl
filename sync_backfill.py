"""Sync the local GDELT backfill into MotherDuck as one conformed article table.

Decision 2026-10-09 (JMD-79 Build Plan v2, M6.5). The backfill previously reached
the dashboard only as pre-aggregated tables, so the warehouse itself had no
article-level history (the chatbot and any direct query saw nothing pre-2026).

Behaviour:
- Windows-filtered: only `published_at >= WINDOW_START` is loaded (GDELT's
  precise-publish-timestamp is occasionally garbage reaching back to 1979).
- Insert-only: a backfill row is written only when the article is not already
  present, so the forward pipeline always wins the overlap (Oct 5-9, 2026). Its
  GDELT observation is still recorded in article_source.
- Provenance in article_source, one row per (article, pipeline), so the two
  word-count methods (trafilatura tokens vs GDELT wc:) never get silently mixed.
- Idempotent: safe to re-run.

Usage:
    set -a; . ./.env; set +a
    python sync_backfill.py            # uses NEWSSTATS_DB_URL or md:newsstats
    python sync_backfill.py --dry-run  # report counts, write nothing
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import duckdb  # noqa: E402

from newsstats import load  # noqa: E402
from newsstats.author_resolution import canonical_key, clean_name, is_pseudo, split_names  # noqa: E402

WINDOW_START = "2021-10-01"
BACKFILL_DB = "data/gdelt_backfill.duckdb"


def _load_env(path: str = ".env") -> None:
    """Load .env without clobbering real environment variables."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _md_target() -> tuple[str, str]:
    """Return (attach_target, connect_url).

    MotherDuck takes the token through the `motherduck_token` environment variable
    (or a connection URI), not through an ATTACH alias, so keep them separate.
    """
    url = os.environ.get("NEWSSTATS_DB_URL", "md:newsstats")
    token = os.environ.get("motherduck_token") or os.environ.get("MOTHERDUCK_TOKEN")
    if token:
        os.environ["motherduck_token"] = token
    if url.startswith("md:") and token and "motherduck_token" not in url:
        sep = "&" if "?" in url else "?"
        return url, f"{url}{sep}motherduck_token={token}"
    return url, url


def build_byline_map(con) -> int:
    """Resolve every distinct GDELT byline into (raw, order, display, key) rows.

    Uses the same rules as the forward pipeline (author_resolution), so a person's
    byline resolves consistently on both sides. Non-person values are dropped.
    """
    rows = con.execute(
        "SELECT DISTINCT author FROM gdelt_article "
        "WHERE author IS NOT NULL AND published_at >= CAST(? AS TIMESTAMP)",
        [WINDOW_START],
    ).fetchall()
    out: list[tuple[str, int, str, str]] = []
    for (raw,) in rows:
        for order, name in enumerate(split_names(raw)):
            if is_pseudo(name):
                continue
            display = clean_name(name)
            key = canonical_key(display)
            if display and key:
                out.append((raw, order, display, key))
    con.execute("CREATE OR REPLACE TEMP TABLE byline_map(raw TEXT, ord INTEGER, name TEXT, key TEXT)")
    if out:
        con.executemany("INSERT INTO byline_map VALUES (?,?,?,?)", out)
    return len(out)


def sync(con, dry_run: bool = False) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None)
    W = "CAST(? AS TIMESTAMP)"  # keeps the window start as a bound parameter

    # 0. forward observations first, so the article's own pipeline is recorded
    if not dry_run:
        con.execute(
            "INSERT INTO md.article_source (article_id, source_type, first_seen_at, "
            "extraction_method, extraction_confidence, raw_word_count) "
            "SELECT article_id, source_type, first_seen_at, extraction_method, "
            "extraction_confidence, word_count "
            "FROM md.article ON CONFLICT DO NOTHING"
        )

    # 1. conformed article rows (backfill only where absent; forward wins overlap)
    if not dry_run:
        con.execute(
            f"""
            INSERT INTO md.article
                (article_id, outlet_id, url, title, published_at, category, language,
                 word_count, word_count_source, metric_completeness, source_type,
                 extraction_method, extraction_confidence, first_seen_at, last_seen_at)
            SELECT g.article_id, g.outlet_id, g.url, g.title, g.published_at, NULL, NULL,
                   g.word_count, 'archive', 'full', 'gdelt', 'gdelt_gkg', NULL, ?, ?
            FROM gdelt_article g
            WHERE g.published_at >= {W}
              AND g.word_count IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM md.article a WHERE a.article_id = g.article_id)
              AND NOT EXISTS (SELECT 1 FROM md.article a WHERE a.url = g.url)
            """,
            [now, now, WINDOW_START],
        )

    # 2. authors for the loaded backfill rows (per-outlet id, consistent with forward)
    if not dry_run:
        con.execute(
            f"""
            INSERT INTO md.author (author_id, outlet_id, canonical_name, first_seen_at, last_seen_at)
            SELECT DISTINCT md5(g.outlet_id || '|' || b.key), g.outlet_id, min(b.name), ?, ?
            FROM gdelt_article g
            JOIN byline_map b ON b.raw = g.author
            WHERE g.published_at >= {W}
              AND g.article_id IN (SELECT article_id FROM md.article WHERE source_type = 'gdelt')
            GROUP BY md5(g.outlet_id || '|' || b.key), g.outlet_id
            ON CONFLICT DO NOTHING
            """,
            [now, now, WINDOW_START],
        )

        con.execute(
            f"""
            INSERT INTO md.article_author (article_id, author_id, author_order)
            SELECT g.article_id, md5(g.outlet_id || '|' || b.key), b.ord
            FROM gdelt_article g
            JOIN byline_map b ON b.raw = g.author
            WHERE g.published_at >= {W}
              AND g.article_id IN (SELECT article_id FROM md.article WHERE source_type = 'gdelt')
            ON CONFLICT DO NOTHING
            """,
            [WINDOW_START],
        )

    # 3. GDELT observation for every in-window row (including overlap rows)
    if not dry_run:
        con.execute(
            f"""
            INSERT INTO md.article_source
                (article_id, source_type, first_seen_at, extraction_method,
                 extraction_confidence, raw_word_count)
            SELECT g.article_id, 'gdelt', ?, 'gdelt_gkg', NULL, g.word_count
            FROM gdelt_article g
            WHERE g.published_at >= {W}
              AND g.article_id IN (SELECT article_id FROM md.article)
            ON CONFLICT DO NOTHING
            """,
            [now, WINDOW_START],
        )

    stats = {
        "articles_total": con.execute("SELECT count(*) FROM md.article").fetchone()[0],
        "articles_archive": con.execute(
            "SELECT count(*) FROM md.article WHERE word_count_source = 'archive'"
        ).fetchone()[0],
        "articles_derived": con.execute(
            "SELECT count(*) FROM md.article WHERE word_count_source = 'derived'"
        ).fetchone()[0],
        "authors_total": con.execute("SELECT count(*) FROM md.author").fetchone()[0],
        "links_total": con.execute("SELECT count(*) FROM md.article_author").fetchone()[0],
        "sources_total": con.execute("SELECT count(*) FROM md.article_source").fetchone()[0],
        "bylines_mapped": con.execute("SELECT count(*) FROM byline_map").fetchone()[0],
        "dry_run": dry_run,
    }
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync the GDELT backfill into MotherDuck")
    ap.add_argument("--db", default=None, help="backfill DuckDB path")
    ap.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    args = ap.parse_args()
    _load_env()

    bf_path = args.db or BACKFILL_DB
    md_target, md_url = _md_target()

    # schema first, on its own connection to MotherDuck
    mdc = duckdb.connect(md_url)
    load.init_schema(mdc)
    mdc.close()

    con = duckdb.connect(bf_path)
    con.execute(f"ATTACH '{md_target}' AS md")
    try:
        mapped = build_byline_map(con)
        print(f"bylines mapped: {mapped}")
        stats = sync(con, dry_run=args.dry_run)
        for k, v in stats.items():
            print(f"  {k}: {v}")

        if not args.dry_run:
            run_id = f"sync-{uuid.uuid4().hex[:8]}"
            now = datetime.now(UTC).replace(tzinfo=None)
            con.execute(
                "INSERT INTO md.ingest_run (run_id, started_at, finished_at, rows_in, rows_flagged, status)"
                " VALUES (?,?,?,?,?,?)",
                [run_id, now, now, stats["articles_archive"], 0, "ok"],
            )
            con.execute(
                "INSERT INTO md.dq_result (run_id, check_name, passed, detail) VALUES (?,?,?,?)",
                [run_id, "backfill_sync_rows", stats["articles_archive"] > 0,
                 f"{stats['articles_archive']} archive rows in the conformed article table"],
            )
            print(f"  recorded ingest_run {run_id}")
    finally:
        con.close()

    # marts are created in MotherDuck, so build them on a MotherDuck connection
    if not args.dry_run:
        from newsstats.metrics import build_marts

        mdc = duckdb.connect(md_url)
        print(f"  marts rebuilt: {build_marts(mdc)}")
        mdc.close()


if __name__ == "__main__":
    main()
