"""Extract structured article fields from raw HTML.

trafilatura is primary for text/title/date/author. JSON-LD and meta tags are
fallbacks for author, category, and date. word_count is always derived from the
extracted body. We measure the body; we never trust a paywall flag to mean
truncation.
"""

from __future__ import annotations

import json
import re

import trafilatura

from newsstats.models import WORD_COUNT_DERIVED, ExtractedArticle
from newsstats.normalize import parse_byline


def _jsonld_nodes(html: str) -> list[dict]:
    nodes = []
    for m in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html, re.S | re.I):
        try:
            d = json.loads(m.strip())
        except Exception:
            continue
        for node in d if isinstance(d, list) else [d]:
            if isinstance(node, dict):
                nodes.append(node)
    return nodes


def _article_nodes(html: str) -> list[dict]:
    return [n for n in _jsonld_nodes(html) if "Article" in str(n.get("@type", ""))]


def _jsonld_author(html: str) -> str | None:
    for node in _article_nodes(html):
        a = node.get("author")
        if isinstance(a, str) and a:
            return a
        if isinstance(a, dict) and a.get("name"):
            return a["name"]
        if isinstance(a, list):
            parts: list[str] = []
            for x in a:
                if isinstance(x, dict) and x.get("name"):
                    parts.append(str(x["name"]))
                elif isinstance(x, str) and x:
                    parts.append(x)
            if parts:
                return ", ".join(parts)
    return None


def _jsonld_section(html: str) -> str | None:
    for node in _article_nodes(html):
        sec = node.get("articleSection")
        if isinstance(sec, str) and sec:
            return sec
        if isinstance(sec, list) and sec:
            return sec[0]
    return None


def _jsonld_title(html: str) -> str | None:
    for node in _article_nodes(html):
        h = node.get("headline")
        if isinstance(h, str) and h:
            return h
        if isinstance(h, dict) and h.get("name"):
            return h["name"]
    return None


def _jsonld_date(html: str) -> str | None:
    for node in _article_nodes(html):
        d = node.get("datePublished") or node.get("dateCreated")
        if isinstance(d, str) and d:
            return d
    return None


def _meta(html: str, *names: str) -> str | None:
    joined = "|".join(re.escape(n) for n in names)
    pat = r'<meta[^>]+(?:name|property)="(?:' + joined + r')"[^>]*content="([^"]+)"'
    for m in re.findall(pat, html, re.I):
        if m and len(m) < 300:
            return m
    return None


def _meta_author(html: str) -> str | None:
    return _meta(html, "author", "article:author", "dc.creator", "dcterms.creator",
                 "sailthru.author", "parsely-author")


def _meta_section(html: str) -> str | None:
    return _meta(html, "article:section", "section", "category", "keywords")


def _meta_title(html: str) -> str | None:
    return _meta(html, "og:title", "title")


def _meta_date(html: str) -> str | None:
    return _meta(html, "article:published_time", "dc.date", "dcterms.date",
                 "date", "publish-date", "parsely-pub-date")


def _confidence(text: str, authors: list[str], date: str | None) -> float:
    c = 0.3
    if len(text) >= 400:
        c += 0.3
    if authors:
        c += 0.2
    if date:
        c += 0.2
    return round(min(c, 1.0), 2)


def extract_article(html: str, url: str) -> ExtractedArticle:
    doc = trafilatura.bare_extraction(html, url=url)
    text, title, author_raw, date, language = "", None, None, None, None
    method = "trafilatura"
    if doc is not None:
        text = doc.text or ""
        title = doc.title
        author_raw = doc.author
        date = doc.date
        language = getattr(doc, "language", None)

    jsonld_author = _jsonld_author(html)
    if not author_raw:
        author_raw = jsonld_author or _meta_author(html)
    category = _jsonld_section(html) or _meta_section(html)
    if not title:
        title = _jsonld_title(html) or _meta_title(html)
    if not date:
        date = _jsonld_date(html) or _meta_date(html)
    if not language:
        language = "en"
    if not text and (jsonld_author or _jsonld_section(html)):
        method = "json-ld"

    authors = parse_byline(author_raw)
    word_count = len(text.split())
    return ExtractedArticle(
        url=url,
        title=title,
        authors=authors,
        published_at=date,
        category=category,
        language=language,
        text=text,
        word_count=word_count,
        word_count_source=WORD_COUNT_DERIVED,
        extraction_method=method,
        extraction_confidence=_confidence(text, authors, date),
    )
