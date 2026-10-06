"""Frozen canonical shapes and id helpers. Owned by the interface freeze.

These dataclasses are the contract between every module. Do not change fields
without updating docs/INTERFACES.md and re-freezing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

WORD_COUNT_NATIVE = "native"
WORD_COUNT_DERIVED = "derived"
COMPLETENESS_FULL = "full"
COMPLETENESS_VOLUME = "volume_only"

# Query params that identify a visit, not an article. Dropped for stable ids.
_TRACKING_KEYS = {
    "ns_mchannel", "ns_campaign", "ito", "fbclid", "gclid",
    "ocid", "cmpid", "ref", "oc", "mc_cid", "mc_eid",
}


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in _TRACKING_KEYS


def canonicalize_url(url: str) -> str:
    """Strip tracking params and fragment; normalize scheme/host for stable ids."""
    parts = urlsplit(url.strip())
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)]
    host = parts.netloc.lower()
    path = parts.path if parts.path not in ("", "/") else "/"
    scheme = (parts.scheme or "https").lower()
    return urlunsplit((scheme, host, path, urlencode(kept), ""))


def article_id_for(url: str) -> str:
    return hashlib.md5(canonicalize_url(url).encode()).hexdigest()


def author_id_for(outlet_id: str, normalized_name: str) -> str:
    key = f"{outlet_id}|{normalized_name.strip().lower()}"
    return hashlib.md5(key.encode()).hexdigest()


@dataclass(frozen=True)
class SourceConfig:
    outlet_id: str
    name: str
    domain: str
    discovery: str
    feed_url: str
    notes: str = ""
    category_map: dict = field(default_factory=dict)
    skip_path_prefixes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DiscoveredArticle:
    outlet_id: str
    url: str
    title: str | None
    published_at: str | None
    category: str | None
    discovered_at: str


@dataclass(frozen=True)
class ExtractedArticle:
    url: str
    title: str | None
    authors: list[str]
    published_at: str | None
    category: str | None
    language: str | None
    text: str
    word_count: int
    word_count_source: str
    extraction_method: str
    extraction_confidence: float


@dataclass(frozen=True)
class CanonicalArticle:
    article_id: str
    outlet_id: str
    url: str
    title: str | None
    authors: list[str]
    published_at: str | None
    category: str | None
    language: str | None
    word_count: int | None
    word_count_source: str
    metric_completeness: str
    source_type: str
    extraction_method: str
    extraction_confidence: float
    first_seen_at: str
    last_seen_at: str
