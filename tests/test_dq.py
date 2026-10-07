from dataclasses import replace
from datetime import UTC, datetime

from newsstats.dq import run_checks
from newsstats.models import (
    COMPLETENESS_FULL,
    WORD_COUNT_DERIVED,
    CanonicalArticle,
    SourceConfig,
)

_BASE = CanonicalArticle(
    article_id="a" * 32,
    outlet_id="fox",
    url="https://www.foxnews.com/x/y",
    title="T",
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


def _src() -> SourceConfig:
    return SourceConfig("fox", "Fox News", "foxnews.com", "rss", "https://x", "")


def _article(**kw) -> CanonicalArticle:
    return replace(_BASE, **kw)


NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)


def _res(checks, name):
    return {c.check_name: c for c in checks}[name]


def test_freshness_fails_when_nothing_discovered():
    assert _res(run_checks(_src(), [], 0, now=NOW), "freshness").passed is False


def test_word_count_bounds():
    bad = [
        _article(word_count=0),
        _article(word_count=25000),
    ]
    for a in bad:
        assert _res(run_checks(_src(), [a], 1, now=NOW), "word_count_bounds").passed is False
    assert _res(run_checks(_src(), [_article(word_count=500)], 1, now=NOW), "word_count_bounds").passed


def test_null_required_keys():
    assert _res(run_checks(_src(), [_article(url="")], 1, now=NOW), "null_required_keys").passed is False


def test_future_dates():
    fut = _article(published_at="2030-01-01T00:00:00+00:00")
    assert _res(run_checks(_src(), [fut], 1, now=NOW), "future_dates").passed is False


def test_duplicate_ids():
    assert _res(run_checks(_src(), [_article(), _article()], 2, now=NOW), "duplicate_ids").passed is False


def test_all_clean_passes():
    assert all(c.passed for c in run_checks(_src(), [_article()], 1, now=NOW))
