"""Discover article URLs from a source's RSS feed or Google News sitemap.

Does not fetch article bodies, only discovers URLs plus whatever the feed
itself carries (title, date, category). Feed links are stripped of whitespace
because some outlets (Daily Mail) pad them.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import feedparser

from newsstats import fetch
from newsstats.models import DiscoveredArticle, SourceConfig

_EXCLUDE_PATH = re.compile(
    r"/(feed|rss|tag|topics|author|staff|about|contact|subscribe|newsletter)/?$", re.I
)
_SIGNUP = re.compile(r"sign-?up", re.I)


def _looks_like_article(url: str, skip_prefixes: tuple = ()) -> bool:
    path = urlparse(url).path
    if len(path.strip("/")) <= 6 or _EXCLUDE_PATH.search(path):
        return False
    if _SIGNUP.search(path):
        return False
    return not any(path.startswith(p) for p in skip_prefixes)


def _entry_date(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=UTC).isoformat()
            except Exception:
                pass
    return entry.get("published") or entry.get("updated")


def _entry_category(entry) -> str | None:
    tags = entry.get("tags")
    if tags and isinstance(tags, list) and tags[0].get("term"):
        return tags[0]["term"]
    return entry.get("category")


def _from_feed(source: SourceConfig, body: str, limit: int | None) -> list[DiscoveredArticle]:
    parsed = feedparser.parse(body)
    now = datetime.now(UTC).isoformat()
    out: list[DiscoveredArticle] = []
    for e in parsed.entries:
        link = (e.get("link") or "").strip()
        if not link or not _looks_like_article(link, tuple(source.skip_path_prefixes)):
            continue
        out.append(
            DiscoveredArticle(
                outlet_id=source.outlet_id,
                url=link,
                title=e.get("title"),
                published_at=_entry_date(e),
                category=_entry_category(e),
                discovered_at=now,
            )
        )
        if limit and len(out) >= limit:
            break
    return out


_URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.S)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
_PUB = re.compile(r"<news:publication_date>\s*(.*?)\s*</news:publication_date>", re.S)


def _from_sitemap(source: SourceConfig, body: str, limit: int | None) -> list[DiscoveredArticle]:
    now = datetime.now(UTC).isoformat()
    out: list[DiscoveredArticle] = []
    for block in _URL_BLOCK.findall(body):
        m = _LOC.search(block)
        if not m:
            continue
        link = m.group(1).strip()
        if not _looks_like_article(link, tuple(source.skip_path_prefixes)):
            continue
        pub = _PUB.search(block)
        out.append(
            DiscoveredArticle(
                outlet_id=source.outlet_id,
                url=link,
                title=None,
                published_at=pub.group(1).strip() if pub else None,
                category=None,
                discovered_at=now,
            )
        )
        if limit and len(out) >= limit:
            break
    return out


def discover(source: SourceConfig, limit: int | None = None) -> list[DiscoveredArticle]:
    body = fetch.fetch_url(source.feed_url)
    if source.discovery == "sitemap":
        return _from_sitemap(source, body, limit)
    return _from_feed(source, body, limit)
