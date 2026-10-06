import pytest

from newsstats.normalize import parse_byline


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("", []),
        ("By Jane Doe", ["Jane Doe"]),
        ("Jane Doe", ["Jane Doe"]),
        ("Jane Doe and John Smith", ["Jane Doe", "John Smith"]),
        ("Jane Doe, John Smith", ["Jane Doe", "John Smith"]),
        ("By Jane Doe, CNN", ["Jane Doe"]),
        ("Jane Doe, Reuters", ["Jane Doe"]),
        ("By Jane Doe and John Smith, Daily Mail", ["Jane Doe", "John Smith"]),
        ("Staff", []),
        ("CNN Wire", []),
        ("Reuters", []),
        ("Associated Press", []),
    ],
)
def test_parse_byline(raw, expected):
    assert parse_byline(raw) == expected
