"""Load canonical rows into DuckDB (local file) or MotherDuck.

Connection target comes from NEWSSTATS_DB_URL or --db. Local file by default.
MotherDuck uses the same engine with an "md:" prefix, e.g.
md:newsstats?motherduck_token=...
Upserts are idempotent: content-hash primary keys + ON CONFLICT.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from newsstats.models import CanonicalArticle, SourceConfig, author_id_for

DEFAULT_DB = "data/warehouse.duckdb"
_MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def connect(db_url: str | None = None):
    url = db_url or os.environ.get("NEWSSTATS_DB_URL", DEFAULT_DB)
    if url.endswith(".duckdb"):
        Path(url).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(url)


def init_schema(conn) -> None:
    for f in sorted(_MIGRATIONS.glob("*.sql")):
        conn.execute(f.read_text())


def _to_ts(value):
    """Parse to a naive UTC datetime. DuckDB TIMESTAMP is naive, and inserting a
    tz-aware datetime silently converts to the session's local zone (shifting the
    date), so we normalize to UTC wall-clock and drop the offset before storing."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip().replace("Z", "+00:00")
        dt = None
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def upsert(conn, source: SourceConfig, rows: list[CanonicalArticle], run_id: str, started_at: str) -> int:
    conn.execute(
        "INSERT INTO outlet (outlet_id,name,domain,discovery,feed_url,notes) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT (outlet_id) DO NOTHING",
        [source.outlet_id, source.name, source.domain, source.discovery, source.feed_url, source.notes],
    )
    for r in rows:
        conn.execute(
            """INSERT INTO article (article_id,outlet_id,url,title,published_at,category,language,
                   word_count,word_count_source,metric_completeness,source_type,extraction_method,
                   extraction_confidence,first_seen_at,last_seen_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT (article_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,
                   word_count=excluded.word_count, extraction_confidence=excluded.extraction_confidence""",
            [
                r.article_id, r.outlet_id, r.url, r.title, _to_ts(r.published_at), r.category,
                r.language, r.word_count, r.word_count_source, r.metric_completeness, r.source_type,
                r.extraction_method, r.extraction_confidence, _to_ts(r.first_seen_at), _to_ts(r.last_seen_at),
            ],
        )
        for order, name in enumerate(r.authors):
            aid = author_id_for(r.outlet_id, name)
            conn.execute(
                "INSERT INTO author (author_id,outlet_id,canonical_name,first_seen_at,last_seen_at)"
                " VALUES (?,?,?,?,?) ON CONFLICT (author_id)"
                " DO UPDATE SET last_seen_at=excluded.last_seen_at",
                [aid, r.outlet_id, name, _to_ts(r.first_seen_at), _to_ts(r.last_seen_at)],
            )
            conn.execute(
                "INSERT INTO article_author (article_id,author_id,author_order) VALUES (?,?,?)"
                " ON CONFLICT DO NOTHING",
                [r.article_id, aid, order],
            )
    conn.execute(
        "INSERT INTO ingest_run (run_id,started_at,finished_at,rows_in,rows_flagged,status)"
        " VALUES (?,?,?,?,?,?)",
        [run_id, _to_ts(started_at), datetime.now().isoformat(), len(rows), 0, "ok"],
    )
    return len(rows)
