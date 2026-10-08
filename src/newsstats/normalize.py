"""Byline parsing and merge into the canonical shape."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from newsstats.category import normalize_category
from newsstats.models import (
    COMPLETENESS_FULL,
    CanonicalArticle,
    DiscoveredArticle,
    ExtractedArticle,
    SourceConfig,
    article_id_for,
    canonicalize_url,
)

# Tokens that are outlets, wire services, or roles, not people. Dropped.
_NON_PERSON = {
    "staff", "wire", "wires", "cnn wire", "reuters", "associated press", "ap",
    "afp", "agence france-presse", "press association", "newsroom", "editorial board",
    "cnn", "bbc", "bbc news", "fox news", "daily mail", "mailonline", "the sun",
    "the independent", "the guardian", "guardian staff", "agencies", "news team",
    "washington post", "new york post", "nbc news", "cbs news", "abc news",
    "bloomberg", "staff writers", "correspondent", "guest", "anonymous",
    "today", "today show", "wire service", "news desk", "editorial staff",
    "guardian staff reporter", "staff reporter", "senior reporter", "news reporter",
    "fox news radio", "conde nast", "guardian community team", "via ap news wire",
    "wire staff", "ap wire", "news wire",
}

_ROLE_PREFIXES = ("news editor", "editor", "senior", "staff writer", "contributing")


def parse_byline(raw: str | None) -> list[str]:
    """Deterministic stage-1 byline parse. "By Jane Doe, CNN" -> ["Jane Doe"]."""
    if not raw:
        return []
    s = re.sub(r"\s+", " ", raw.strip())
    if not s:
        return []
    s = re.sub(r"^[Bb]y\s+", "", s)
    parts = re.split(r"\s+[Aa]nd\s+", s)
    tokens: list[str] = []
    for part in parts:
        tokens.extend(part.split(","))
    names: list[str] = []
    for tok in tokens:
        name = re.sub(r"\s+", " ", tok).strip().strip(".;:")
        if not name:
            continue
        low = name.lower()
        if low in _NON_PERSON:
            continue
        if any(low.startswith(rp) for rp in _ROLE_PREFIXES) and len(name.split()) > 3:
            continue
        names.append(name)
    return names


def _category_from_url(url: str, category_map: dict) -> str | None:
    if not category_map:
        return None
    path = urlsplit(url).path
    for prefix, cat in category_map.items():
        if path.startswith(prefix):
            return cat
    return None


def to_canonical(
    discovered: DiscoveredArticle,
    extracted: ExtractedArticle,
    source: SourceConfig,
    seen_at: str,
) -> CanonicalArticle:
    category = normalize_category(
        extracted.category
        or discovered.category
        or _category_from_url(discovered.url, source.category_map)
    )
    published = extracted.published_at or discovered.published_at
    return CanonicalArticle(
        article_id=article_id_for(discovered.url),
        outlet_id=source.outlet_id,
        url=canonicalize_url(discovered.url),
        title=extracted.title or discovered.title,
        authors=extracted.authors,
        published_at=published,
        category=category,
        language=extracted.language,
        word_count=extracted.word_count,
        word_count_source=extracted.word_count_source,
        metric_completeness=COMPLETENESS_FULL,
        source_type=source.discovery,
        extraction_method=extracted.extraction_method,
        extraction_confidence=extracted.extraction_confidence,
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
