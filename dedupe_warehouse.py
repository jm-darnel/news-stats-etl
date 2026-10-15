"""One-time warehouse dedup + timestamp hygiene (JMD-79, decision 2026-10-14).

Phase A - CNN host-variant merge. GDELT archives the same article under
us.cnn.com / edition.cnn.com / www.cnn.com; article_id = md5(canonical url)
keeps the host, so ~125k duplicate rows inflated every CNN metric (49.8% of the
CNN archive). Merge rule: within each normalized-URL group (us/edition ->
www), the www twin wins; else earliest first_seen. Author links and
article_source provenance move to the survivor; variant rows are deleted.
canonicalize_url is intentionally UNCHANGED: broadening it would invalidate
every stored article_id and break re-ingestion idempotency.

Phase B - garbage-timestamp nulling. Clusters of >=25 same-outlet rows sharing
one exact minute, all first_seen within 60s (one crawl batch), non-live majority:
GDELT stamped a whole file's records with the file timestamp (the 2023-11-16
"peak day" was 3,065 Washington Examiner rows at 15:28). Their published_at is
set to NULL so they leave time series but keep counting toward totals.
Date-precision outlets (Fox: 75.7% of archive at 00:00:00) and live-post sibling
captures are NOT touched.

Idempotent: re-running re-derives empty work sets.

Usage:
    set -a; . ./.env; set +a
    python dedupe_warehouse.py --dry-run   # counts only, writes nothing
    python dedupe_warehouse.py
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

CNN_NU = (
    "regexp_replace(url, '^https://(us|edition)\\.cnn\\.com', 'https://www.cnn.com')"
)
GARBAGE_CLUSTER = """
    count(*) >= 25
    AND (max(first_seen_at) - min(first_seen_at)) <= INTERVAL 60 SECOND
    AND extract(minute FROM published_at) != 0
    AND sum(CASE WHEN content_type = 'live_post' THEN 1 ELSE 0 END) < count(*) / 2.0
"""


def _load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _connect():
    url = os.environ.get("NEWSSTATS_DB_URL", "md:newsstats")
    token = os.environ.get("motherduck_token") or os.environ.get("MOTHERDUCK_TOKEN")
    if url.startswith("md:") and token and "motherduck_token" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}motherduck_token={token}"
    return duckdb.connect(url)


def build_worksets(con) -> dict:
    """Derive merge + garbage work sets as temp tables. Returns headline counts."""
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ranked AS
        SELECT n.article_id, n.nu, x.url, x.first_seen_at, x.source_type,
               x.word_count, x.word_count_source,
               row_number() OVER (
                   PARTITION BY n.nu
                   ORDER BY (x.url = n.nu) DESC, x.first_seen_at
               ) AS rn
        FROM article x
        JOIN (SELECT article_id, {CNN_NU} AS nu
              FROM article WHERE outlet_id = 'cnn') n
            ON n.article_id = x.article_id
        WHERE x.outlet_id = 'cnn'
          AND n.nu IN (SELECT {CNN_NU} AS nu
                       FROM article WHERE outlet_id = 'cnn'
                       GROUP BY 1 HAVING count(*) > 1)
    """)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE surv AS "
        "SELECT nu, article_id AS survivor_id FROM ranked WHERE rn = 1"
    )
    con.execute(
        "CREATE OR REPLACE TEMP TABLE del AS "
        "SELECT r.article_id, r.nu, s.survivor_id "
        "FROM ranked r JOIN surv s USING (nu) WHERE r.rn > 1 AND r.url <> r.nu"
    )
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE garbage AS
        SELECT outlet_id, published_at, count(*) AS n
        FROM article WHERE published_at IS NOT NULL
        GROUP BY outlet_id, published_at
        HAVING {GARBAGE_CLUSTER}
    """)
    return {
        "twin_groups": con.execute("SELECT count(*) FROM surv").fetchone()[0],
        "cnn_rows_to_delete": con.execute("SELECT count(*) FROM del").fetchone()[0],
        "wc_conflicts": con.execute("""
            SELECT count(*) FROM del d
            JOIN ranked v ON v.article_id = d.article_id
            JOIN ranked sv ON sv.article_id = d.survivor_id
            WHERE v.word_count IS NOT NULL AND sv.word_count IS NOT NULL
              AND v.word_count <> sv.word_count
        """).fetchone()[0],
        "author_links_to_move": con.execute("""
            SELECT count(*) FROM article_author aa JOIN del d ON d.article_id = aa.article_id
        """).fetchone()[0],
        "article_source_rows_to_move": con.execute("""
            SELECT count(*) FROM article_source s JOIN del d ON d.article_id = s.article_id
        """).fetchone()[0],
        "garbage_clusters": con.execute("SELECT count(*) FROM garbage").fetchone()[0],
        "garbage_rows": con.execute("SELECT coalesce(sum(n),0) FROM garbage").fetchone()[0],
        "garbage_by_outlet": con.execute("""
            SELECT o.name, g.n FROM garbage g JOIN outlet o USING (outlet_id)
            ORDER BY g.n DESC
        """).fetchall(),
    }


def merge_cnn(con) -> int:
    """Move links/provenance to survivors, delete variant rows. Returns deleted."""
    # author links: re-point at the survivor, drop exact duplicates
    con.execute("""
        INSERT INTO article_author (article_id, author_id, author_order)
        SELECT d.survivor_id, aa.author_id, aa.author_order
        FROM article_author aa JOIN del d ON d.article_id = aa.article_id
        ON CONFLICT DO NOTHING
    """)
    # provenance: survivor gains the variant's observations
    con.execute("""
        INSERT INTO article_source
            (article_id, source_type, first_seen_at, extraction_method,
             extraction_confidence, raw_word_count)
        SELECT d.survivor_id, s.source_type, s.first_seen_at,
               s.extraction_method, s.extraction_confidence, s.raw_word_count
        FROM article_source s JOIN del d ON d.article_id = s.article_id
        ON CONFLICT DO NOTHING
    """)
    con.execute("DELETE FROM article_author WHERE article_id IN (SELECT article_id FROM del)")
    con.execute("DELETE FROM article_source WHERE article_id IN (SELECT article_id FROM del)")
    con.execute("DELETE FROM article WHERE article_id IN (SELECT article_id FROM del)")
    return con.execute("SELECT count(*) FROM del").fetchone()[0]


def null_garbage_timestamps(con) -> int:
    con.execute("""
        UPDATE article SET published_at = NULL
        FROM garbage g
        WHERE article.outlet_id = g.outlet_id
          AND article.published_at = g.published_at
    """)
    return con.execute("SELECT coalesce(sum(n),0) FROM garbage").fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="CNN variant merge + garbage timestamp nulling")
    ap.add_argument("--dry-run", action="store_true", help="print work-set counts, write nothing")
    args = ap.parse_args()
    _load_env()
    con = _connect()
    try:
        stats = build_worksets(con)
        for k, v in stats.items():
            print(f"  {k}: {v}")
        if args.dry_run:
            print("dry-run: nothing written")
            return

        deleted = merge_cnn(con)
        nulled = null_garbage_timestamps(con)
        print(f"  cnn rows deleted: {deleted}")
        print(f"  garbage timestamps nulled: {nulled}")

        from newsstats.metrics import build_marts

        print(f"  marts rebuilt: {build_marts(con)}")

        run_id = f"dedupe-{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC).replace(tzinfo=None)
        con.execute(
            "INSERT INTO ingest_run (run_id, started_at, finished_at, rows_in, rows_flagged, status)"
            " VALUES (?,?,?,?,?,?)",
            [run_id, now, now, deleted, nulled, "ok"],
        )
        con.execute(
            "INSERT INTO dq_result (run_id, check_name, passed, detail) VALUES (?,?,?,?)",
            [run_id, "cnn_variant_merge", deleted > 0,
             f"{deleted} variant rows merged; {nulled} garbage timestamps nulled"],
        )
        print(f"  recorded ingest_run {run_id}")

        for label, q in [
            ("cnn total", "SELECT count(*) FROM article WHERE outlet_id='cnn'"),
            ("corpus total", "SELECT count(*) FROM article"),
            ("new peak day", """
                SELECT CAST(published_at AS DATE), count(*) FROM article
                WHERE published_at IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 3
            """),
        ]:
            print(f"  verify {label}: {con.execute(q).fetchall()}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
