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


def test_splits_wire_attribution():
    assert split_names("Aamer Madhani / AP") == ["Aamer Madhani"]
    assert split_names("Jane Roe / Reuters") == ["Jane Roe"]


def test_strips_mail_on_sunday_suffix():
    assert split_names("A.N. Wilson For The Daily Mail") == ["A.N. Wilson"]
    assert split_names("A.n. Wilson For The Mail On Sunday") == ["A.n. Wilson"]


def test_dedup_is_case_insensitive():
    assert split_names("Maureen Chowdhury;MAUREEN CHOWDHURY") == ["Maureen Chowdhury"]


def test_clean_name_strips_whitespace_and_punct():
    assert clean_name("  Joe Biden  ,") == "Joe Biden"
    assert clean_name("<a href='/x'>Joe Biden</a>") == "Joe Biden"


def test_drops_archive_desk_bylines():
    # the GDELT-side leak found in agg_author_month (2026-10-14)
    assert split_names("US NEWS REPORTER") == []
    assert split_names("SENIOR NEWS REPORTER") == []
    assert split_names("US Senior News Reporter") == []
    assert split_names("DAILY MAIL REPORTER") == []
    assert split_names("FOREIGN NEWS REPORTER") == []
    assert split_names("Associate Showbusiness Editor") == []
    assert split_names("Chief Congressional Correspondent") == []
    assert split_names("Press Association Chief Football Writer") == []
    assert split_names("Associated") == []
    # MailOnline dateline convention: role + "In/At <place>" suffix
    assert split_names("U.S. POLITICAL REPORTER IN WASHINGTON") == []
    assert split_names("Senior U.S. Political Reporter In Belfast") == []
    assert split_names("Senior U.S. Political Reporter") == []  # 'U.S.' dot-normalized
    assert split_names("Political Reporter At Madison Square Garden") == []


def test_keeps_person_behind_role_tail():
    # role descriptors ride on real people's bylines: strip the tail, keep the person
    assert split_names("MARK NICOL DIPLOMACY EDITOR") == ["MARK NICOL"]
    assert split_names("Xantha Leatham Science Correspondent") == ["Xantha Leatham"]
    assert split_names("Molly Clayton Influencer Correspondent") == ["Molly Clayton"]
    assert split_names("POPPY ATKINSON GIBSON - LIFESTYLE REPORTER") == ["POPPY ATKINSON GIBSON"]
    assert split_names("KATELYN CARALLE SENIOR U.S. POLITICAL REPORTER") == ["KATELYN CARALLE"]


def test_drops_desk_brand_bylines():
    assert split_names("CNN Business") == []
    from newsstats.author_resolution import is_pseudo

    assert is_pseudo("The Intercept Briefing")
    # tradeoff (2026-10-14): "Jane Reporter" now keeps person "Jane" — a lone first
    # name is a rare false negative, accepted so real name+role bylines survive
    assert not is_pseudo("Jane Reporter")
    # ordinary multi-word person names must survive
    assert not is_pseudo("Victoria Beckham")
    assert not is_pseudo("Mary O'connor")
