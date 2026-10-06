from newsstats.config import SourceConfigError, get_source, load_sources


def test_load_sources_returns_all_outlets():
    sources = load_sources()
    assert len(sources) == 22
    ids = {s.outlet_id for s in sources}
    assert {"fox", "slate", "cnn", "guardian"} <= ids


def test_every_outlet_has_required_keys():
    for s in load_sources():
        assert s.outlet_id and s.name and s.domain and s.feed_url
        assert s.discovery in ("rss", "sitemap")


def test_get_source():
    s = get_source("fox")
    assert s.domain == "foxnews.com"


def test_get_source_unknown():
    try:
        get_source("nope")
    except SourceConfigError:
        return
    raise AssertionError("expected SourceConfigError")
