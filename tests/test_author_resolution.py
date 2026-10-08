"""Tests for rule-based author resolution."""

from __future__ import annotations

from newsstats.author_resolution import canonical_key, clean_name, split_names


def test_strips_daily_mail_self_duplicate():
    assert split_names("Amelia Wynne;Amelia Wynne For Mailonline") == ["Amelia Wynne"]


def test_unescapes_html_entities():
    assert split_names("Ren&#xE9; Dupont") == ["René Dupont"]


def test_drops_publisher_company():
    assert split_names("Cond&#xE9; Nast") == []  # publisher imprint, not a person


def test_strips_html_anchor():
    assert split_names('<a href="/profiles/aditi-sandal">Aditi Sangal</a>') == ["Aditi Sangal"]


def test_drops_pseudo_and_garbage():
    assert split_names("FOX News Radio") == []
    assert split_names("Guardian staff reporter") == []
    assert split_names("161385360554578") == []
    assert split_names("nickmidtc") == []
    assert split_names("The Associated Press") == []


def test_multi_author_and_suffix_strip():
    out = split_names("Jane Doe;John Smith For Mailonline;For The Guardian")
    assert out == ["Jane Doe", "John Smith"]


def test_accent_folding_key():
    assert canonical_key("Ivana Kottasová") == canonical_key("Ivana Kottasova")


def test_dedup_is_case_insensitive():
    assert split_names("Maureen Chowdhury;MAUREEN CHOWDHURY") == ["Maureen Chowdhury"]


def test_clean_name_strips_whitespace_and_punct():
    assert clean_name("  Joe Biden  ,") == "Joe Biden"
    assert clean_name("<a href='/x'>Joe Biden</a>") == "Joe Biden"
