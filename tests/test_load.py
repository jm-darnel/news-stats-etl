import duckdb
import pytest

from newsstats import load
from newsstats.models import (
    COMPLETENESS_FULL,
    WORD_COUNT_DERIVED,
    CanonicalArticle,
    SourceConfig,
)


@pytest.fixture
def conn(tmp_path):
    con = duckdb.connect(str(tmp_path / "test.duckdb"))
    load.init_schema(con)
    yield con
    con.close()


def _article(outlet_id="fox", url="https://www.foxnews.com/x/y") -> CanonicalArticle:
    return CanonicalArticle(
        article_id="a" * 32,
        outlet_id=outlet_id,
        url=url,
        title="A Title",
        authors=["Jane Doe"],
        published_at="2026-10-06T00:00:00+00:00",
        category=None,
        language="en",
        word_count=100,
        word_count_source=WORD_COUNT_DERIVED,
        metric_completeness=COMPLETENESS_FULL,
        source_type="rss",
        extraction_method="trafilatura",
        extraction_confidence=1.0,
        first_seen_at="2026-10-06T00:00:00+00:00",
        last_seen_at="2026-10-06T00:00:00+00:00",
    )


def _src(outlet_id="fox") -> SourceConfig:
    return SourceConfig(outlet_id, "Fox News", "foxnews.com", "rss", "https://x", "")


def test_upsert_is_idempotent(conn):
    load.upsert(conn, _src(), [_article()], "run1", "2026-10-06T00:00:00+00:00")
    load.upsert(conn, _src(), [_article()], "run2", "2026-10-06T01:00:00+00:00")
    assert conn.execute("SELECT count(*) FROM article").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM author").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM article_author").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM outlet").fetchone()[0] == 1


def test_upsert_skips_already_seen(conn):
    from dataclasses import replace
    from datetime import datetime

    a1 = _article()
    assert load.upsert(conn, _src(), [a1], "run1", "2026-10-06T00:00:00+00:00") == 1
    a2 = replace(a1, last_seen_at="2026-10-07T00:00:00+00:00")
    assert load.upsert(conn, _src(), [a2], "run2", "2026-10-07T00:00:00+00:00") == 0
    assert conn.execute("SELECT count(*) FROM article").fetchone()[0] == 1
    # re-discovery is a no-op: last_seen stays at first ingestion, no re-write
    last_seen = conn.execute("SELECT last_seen_at FROM article").fetchone()[0]
    first_seen = conn.execute("SELECT first_seen_at FROM article").fetchone()[0]
    assert last_seen == datetime(2026, 10, 6)
    assert first_seen == datetime(2026, 10, 6)


def test_upsert_writes_only_new_rows(conn):
    from dataclasses import replace

    from newsstats.models import article_id_for

    a1 = _article()
    url2 = "https://www.foxnews.com/a/b"
    a2 = replace(a1, article_id=article_id_for(url2), url=url2, authors=["John Smith"])
    assert load.upsert(conn, _src(), [a1], "run1", "2026-10-06T00:00:00+00:00") == 1
    # second run mixes one already-seen article with one new one
    assert load.upsert(conn, _src(), [a1, a2], "run2", "2026-10-06T01:00:00+00:00") == 1
    assert conn.execute("SELECT count(*) FROM article").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM author").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM article_author").fetchone()[0] == 2
