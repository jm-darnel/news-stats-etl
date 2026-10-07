"""Tests for the GDELT GKG backfill parser."""

from __future__ import annotations

from datetime import datetime

from newsstats.backfill import gkg_timestamps, match_outlet, parse_row
from newsstats.models import article_id_for

DOMAIN_MAP = {"cnn.com": "cnn", "theguardian.com": "guardian"}


def _row(domain="cnn.com", url="https://www.cnn.com/2026/10/05/politics/x/index.html",
         counts="wc:424,c12.1:27", extras=None, date="20261006000000"):
    if extras is None:
        extras = ("<PAGE_AUTHORS>John Doe</PAGE_AUTHORS>"
                  "<PAGE_PRECISEPUBTIMESTAMP>20261005210100</PAGE_PRECISEPUBTIMESTAMP>"
                  "<PAGE_TITLE>Some Title</PAGE_TITLE>")
    r = [""] * 27
    r[1] = date
    r[3] = domain
    r[4] = url
    r[17] = counts
    r[26] = extras
    return r


def test_gkg_timestamps_96_per_day():
    ts = gkg_timestamps(datetime(2026, 10, 6), datetime(2026, 10, 7))
    assert len(ts) == 96
    assert ts[0] == "20261006000000"
    assert ts[-1] == "20261006234500"


def test_match_outlet_exact_and_subdomain():
    assert match_outlet("cnn.com", DOMAIN_MAP) == "cnn"
    assert match_outlet("edition.cnn.com", DOMAIN_MAP) == "cnn"
    assert match_outlet("notcnn.com", DOMAIN_MAP) is None
    assert match_outlet("", DOMAIN_MAP) is None


def test_parse_row_full_extraction():
    rec = parse_row(_row(), DOMAIN_MAP)
    assert rec is not None
    assert rec.outlet_id == "cnn"
    assert rec.word_count == 424
    assert rec.author == "John Doe"
    assert rec.title == "Some Title"
    assert rec.published_at == "2026-10-05 21:01:00"
    assert rec.article_id == article_id_for("https://www.cnn.com/2026/10/05/politics/x/index.html")


def test_parse_row_rejects_other_domain():
    assert parse_row(_row(domain="nytimes.com"), DOMAIN_MAP) is None


def test_parse_row_word_count_missing_and_date_fallback():
    rec = parse_row(_row(counts="c12.1:27", extras="", date="20261006000000"), DOMAIN_MAP)
    assert rec is not None
    assert rec.word_count is None
    assert rec.author is None
    assert rec.published_at == "2026-10-06 00:00:00"  # falls back to V2DATE


def test_parse_row_short_row_returns_none():
    assert parse_row(["x", "y"], DOMAIN_MAP) is None
