"""Acceptance tests for content_type classification (migration 0003)."""

import duckdb
import pytest

from newsstats import load
from newsstats.content_type import ARTICLE, LIST, classify_content
from newsstats.models import CanonicalArticle, SourceConfig, article_id_for


def _src(pattern: str | None = None, oid: str = "latimes") -> SourceConfig:
    return SourceConfig(
        oid, "LA Times", "latimes.com", "rss", "https://x", "",
        list_url_pattern=pattern,
    )


def test_opt_in_outlet_list_url():
    src = _src(r"/(list|listicle)s?/")
    assert classify_content("https://www.latimes.com/food/list/best-tacos", src) == LIST
    assert classify_content("https://www.latimes.com/food/listicles/one", src) == LIST


def test_opt_in_outlet_story_url_is_article():
    src = _src(r"/(list|listicle)s?/")
    assert classify_content("https://www.latimes.com/california/story/2026-10-01/x", src) == ARTICLE


def test_no_pattern_defaults_to_article():
    src = _src(None)
    assert classify_content("https://www.latimes.com/food/list/best-tacos", src) == ARTICLE


def test_case_insensitive():
    src = _src(r"/(list|listicle)s?/", oid="verge")
    assert classify_content("https://www.theverge.com/Gadgets/Best/x", src) == ARTICLE
    assert classify_content("https://www.latimes.com/TRAVEL/LIST/x", _src(r"/(list|listicle)s?/")) == LIST


def test_live_post_pattern():
    from newsstats.content_type import LIVE_POST

    src = SourceConfig("cnn", "CNN", "cnn.com", "sitemap", "https://x", "",
                       live_post_url_pattern="/live-news/")
    assert classify_content(
        "https://www.cnn.com/europe/live-news/ukraine-russia-putin-news-03-01-22/h_abc123", src
    ) == LIVE_POST
    # list pattern wins on priority; live pattern alone promotes to live_post
    assert classify_content("https://www.theverge.com/tech/x", src) == ARTICLE


def test_live_post_without_pattern_is_article():
    src = _src(None)  # LA Times has no live pattern
    assert classify_content("https://www.latimes.com/live-news/x", src) == ARTICLE


def _art(oid: str, url: str, content_type: str) -> CanonicalArticle:
    return CanonicalArticle(
        article_id=article_id_for(url),
        outlet_id=oid,
        url=url,
        title="T",
        authors=["Jane Doe"],
        published_at="2026-10-06T00:00:00+00:00",
        category=None,
        language="en",
        word_count=500,
        word_count_source="derived",
        metric_completeness="full",
        source_type="rss",
        extraction_method="trafilatura",
        extraction_confidence=1.0,
        first_seen_at="2026-10-06T00:00:00+00:00",
        last_seen_at="2026-10-06T00:00:00+00:00",
        content_type=content_type,
    )


@pytest.fixture
def conn(tmp_path):
    con = duckdb.connect(str(tmp_path / "ct.duckdb"))
    load.init_schema(con)
    yield con
    con.close()


def test_upsert_persists_content_type(conn):
    src = _src(r"/(list|listicle)s?/")
    arts = [
        _art("latimes", "https://www.latimes.com/food/list/best-tacos", "list"),
        _art("latimes", "https://www.latimes.com/california/story/x", "article"),
    ]
    load.upsert(conn, src, arts, "r1", "2026-10-06T00:00:00+00:00")
    rows = dict(conn.execute("SELECT url, content_type FROM article").fetchall())
    assert rows["https://www.latimes.com/food/list/best-tacos"] == "list"
    assert rows["https://www.latimes.com/california/story/x"] == "article"


def test_dim_outlet_has_content_type_split(conn):
    src = _src(r"/(list|listicle)s?/")
    arts = [
        _art("latimes", "https://www.latimes.com/food/list/a", "list"),
        _art("latimes", "https://www.latimes.com/california/story/b", "article"),
        _art("latimes", "https://www.latimes.com/california/story/c", "article"),
    ]
    load.upsert(conn, src, arts, "r1", "2026-10-06T00:00:00+00:00")
    from newsstats import metrics

    metrics.build_marts(conn)
    row = conn.execute(
        "SELECT article_count, article_count_list, avg_word_count_articles FROM dim_outlet"
    ).fetchone()
    assert row == (3, 1, 500.0)
