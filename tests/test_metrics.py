from datetime import date

import duckdb
import pytest

from newsstats import load, metrics
from newsstats.models import (
    COMPLETENESS_FULL,
    WORD_COUNT_DERIVED,
    CanonicalArticle,
    SourceConfig,
    article_id_for,
)


def _src(oid="fox") -> SourceConfig:
    return SourceConfig(oid, "Fox", "foxnews.com", "rss", "https://x", "")


def _art(oid, url, published, wc, authors, category="politics") -> CanonicalArticle:
    return CanonicalArticle(
        article_id=article_id_for(url),
        outlet_id=oid,
        url=url,
        title="T",
        authors=authors,
        published_at=published,
        category=category,
        language="en",
        word_count=wc,
        word_count_source=WORD_COUNT_DERIVED,
        metric_completeness=COMPLETENESS_FULL,
        source_type="rss",
        extraction_method="trafilatura",
        extraction_confidence=1.0,
        first_seen_at=published,
        last_seen_at=published,
    )


@pytest.fixture
def conn(tmp_path):
    con = duckdb.connect(str(tmp_path / "m.duckdb"))
    load.init_schema(con)
    yield con
    con.close()


def test_agg_outlet_daily(conn):
    src = _src()
    arts = [
        _art("fox", "https://f.com/1", "2026-10-06T00:00:00+00:00", 100, ["A"]),
        _art("fox", "https://f.com/2", "2026-10-06T00:00:00+00:00", 200, ["B"]),
        _art("fox", "https://f.com/3", "2026-10-07T00:00:00+00:00", 300, ["C"]),
    ]
    load.upsert(conn, src, arts, "r1", "2026-10-06T00:00:00+00:00")
    metrics.build_marts(conn)
    rows = conn.execute(
        "SELECT day, article_count, avg_word_count FROM agg_outlet_daily ORDER BY day"
    ).fetchall()
    assert rows == [(date(2026, 10, 6), 2, 150.0), (date(2026, 10, 7), 1, 300.0)]


def test_dim_author_counts(conn):
    src = _src()
    arts = [
        _art("fox", "https://f.com/1", "2026-10-06T00:00:00+00:00", 100, ["Jane Doe"]),
        _art("fox", "https://f.com/2", "2026-10-06T00:00:00+00:00", 200, ["Jane Doe"]),
        _art("fox", "https://f.com/3", "2026-10-06T00:00:00+00:00", 300, ["John Smith"]),
    ]
    load.upsert(conn, src, arts, "r1", "2026-10-06T00:00:00+00:00")
    metrics.build_marts(conn)
    rows = conn.execute(
        "SELECT canonical_name, article_count, avg_word_count FROM dim_author ORDER BY canonical_name"
    ).fetchall()
    assert rows == [("Jane Doe", 2, 150.0), ("John Smith", 1, 300.0)]


def test_category_backfill(conn):
    src = _src()
    load.upsert(
        conn,
        src,
        [_art("fox", "https://f.com/1", "2026-10-06T00:00:00+00:00", 100, ["A"], category="outkick sports")],
        "r1",
        "2026-10-06T00:00:00+00:00",
    )
    assert conn.execute("SELECT category FROM article").fetchone()[0] == "outkick sports"
    metrics.build_marts(conn)
    assert conn.execute("SELECT category FROM article").fetchone()[0] == "sports"


def test_agg_author_week(conn):
    src = _src()
    arts = [
        _art("fox", "https://f.com/1", "2026-10-06T00:00:00+00:00", 100, ["A"]),
        _art("fox", "https://f.com/2", "2026-10-06T00:00:00+00:00", 200, ["A"]),
    ]
    load.upsert(conn, src, arts, "r1", "2026-10-06T00:00:00+00:00")
    metrics.build_marts(conn)
    row = conn.execute(
        "SELECT canonical_name, article_count, avg_word_count FROM agg_author_week"
    ).fetchone()
    assert row[0] == "A" and row[1] == 2 and row[2] == 150.0
