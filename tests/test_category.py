import pytest

from newsstats.category import normalize_category


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "other"),
        ("", "other"),
        ("Politics", "politics"),
        ("politics, trending", "politics"),
        ("Outkick Sports", "sports"),
        ("tyreek hill, nfl", "sports"),
        ("Television & radio", "entertainment"),
        ("Jurisprudence", "opinion"),
        ("Science", "science"),
        ("US", "us"),
        ("World", "world"),
        ("Health", "health"),
        ("Business", "business"),
        ("Technology", "tech"),
        ("Relationships", "other"),
        ("The Filter", "other"),
        ("cnn fast", "other"),
    ],
)
def test_normalize_category(raw, expected):
    assert normalize_category(raw) == expected
