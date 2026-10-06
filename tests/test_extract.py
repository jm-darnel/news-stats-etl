from pathlib import Path

from newsstats.extract import extract_article

FIXTURE = Path(__file__).parent / "fixtures" / "fixture_article.html"


def test_extract_article_fields():
    out = extract_article(FIXTURE.read_text(), "https://www.slate.com/news-and-politics/2026/10/test.html")
    assert out.word_count > 0
    assert out.title is not None
    assert "Jane Doe" in out.authors
    assert out.category == "Politics"
    assert out.word_count_source == "derived"
    assert out.extraction_method in ("trafilatura", "json-ld", "meta")
    assert 0.0 <= out.extraction_confidence <= 1.0
    assert out.published_at is not None
