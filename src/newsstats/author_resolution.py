"""Rule-based author canonicalization for forward + backfill bylines.

Targets the real garbage observed in the corpus:
- "Amelia Wynne;Amelia Wynne For Mailonline"  -> ["Amelia Wynne"]   (same person twice)
- "Cond&#xE9; Nast"  (HTML entity)             -> "Condé Nast"
- "FOX News Radio" / "161385360554578" / "nickmidtc"  -> dropped

Deliberately rule-based and deterministic. A cheap LLM pass covers the residual
near-duplicates (typos / name variants) afterwards.
"""

from __future__ import annotations

import html
import re
import unicodedata

from .normalize import _NON_PERSON

# "Name For Mailonline" is the Daily-Mail byline convention: strip the publication
# qualifier so "Amelia Wynne" and "Amelia Wynne For Mailonline" collapse to one.
_FOR_SUFFIX = re.compile(
    r"(?:^|\s+)for\s+(mailonline|dailymail\.com|daily\s+mail\s+australia|the\s+conversation"
    r"|the\s+guardian|the\s+sun|cnn|nbc\s+news|fox\s+news|cbs\s+news)", re.I)

_HTML_TAG = re.compile(r"<[^>]+>")

_NUMERIC = re.compile(r"^[\d\s\-]+$")
_BARE_HANDLE = re.compile(r"^[a-z0-9_]{2,24}$")  # a lone lowercase token = username


def clean_name(name: str) -> str:
    n = html.unescape(name or "")
    n = _HTML_TAG.sub(" ", n)  # CNN bylines render as <a href="...">Name</a>
    n = _FOR_SUFFIX.sub("", n)
    n = re.sub(r"\s+", " ", n)
    return n.strip(" \t\r\n.;:,")


def is_pseudo(name: str) -> bool:
    """True if the token is an outlet/wire/role/garbage, not a person."""
    if not name:
        return True
    if _NUMERIC.match(name) or _BARE_HANDLE.match(name):
        return True
    low = canonical_key(name)
    if low in _NON_PERSON or low.removeprefix("the ") in _NON_PERSON:
        return True
    return False


def canonical_key(name: str) -> str:
    """Accent-fold + casefold key for cross-article dedup ('Kottasová' == 'kottasova')."""
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", n).strip().casefold()


def split_names(raw: str | None) -> list[str]:
    """Raw byline -> deduplicated list of clean person names (preserving order)."""
    if not raw:
        return []
    s = html.unescape(raw)
    parts = re.split(r"[;,;&]|\s+and\s+", s)
    names: list[str] = []
    seen: set[str] = set()
    for p in parts:
        n = clean_name(p)
        if not n or is_pseudo(n):
            continue
        k = canonical_key(n)
        if k in seen:
            continue
        seen.add(k)
        names.append(n)
    return names
