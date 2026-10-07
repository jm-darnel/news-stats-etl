"""Map raw article categories (free-form, outlet-specific) to a controlled
vocabulary. This is a heuristic convenience; it collapses messy publisher
sections ("outkick sports", "Television & radio", "politics, trending") into a
small, chartable set.

Bare "us" is handled as a whole token, not a substring (it would otherwise hit
every "business"/"house"/"Russia")."""

from __future__ import annotations

_EXACT: dict[str, str] = {
    "us": "us", "usa": "us", "u.s.": "us", "national": "us",
    "world": "world", "international": "world",
    "science": "science", "health": "health", "business": "business",
    "tech": "tech", "technology": "tech", "politics": "politics",
    "sports": "sports", "opinion": "opinion", "entertainment": "entertainment",
    "culture": "entertainment", "books": "entertainment", "music": "entertainment",
}

# Substring matches (distinctive; no bare "us").
_SUBSTR: list[tuple[str, str]] = [
    ("politics", "politics"), ("white house", "politics"), ("congress", "politics"),
    ("election", "politics"), ("campaign", "politics"), ("government", "politics"),
    ("business", "business"), ("money", "business"), ("econom", "business"),
    ("financ", "business"),
    ("tech", "tech"), ("software", "tech"),
    ("science", "science"), ("space", "science"), ("climate", "science"),
    ("world", "world"), ("international", "world"), ("foreign", "world"),
    ("opinion", "opinion"), ("editorial", "opinion"), ("jurisprudence", "opinion"),
    ("health", "health"), ("wellness", "health"), ("medical", "health"),
    ("sport", "sports"), ("nfl", "sports"), ("mlb", "sports"), ("nba", "sports"),
    ("nhl", "sports"), ("football", "sports"), ("baseball", "sports"),
    ("basketball", "sports"), ("soccer", "sports"), ("outkick", "sports"),
    ("entertainment", "entertainment"), ("movie", "entertainment"), ("film", "entertainment"),
    ("television", "entertainment"), ("music", "entertainment"), ("celebrity", "entertainment"),
    ("showbiz", "entertainment"), ("hollywood", "entertainment"), ("culture", "entertainment"),
]

_US_TOKENS = {"us", "u.s.", "usa"}


def normalize_category(raw: str | None) -> str:
    if not raw:
        return "other"
    s = raw.lower().strip()
    for part in s.split(","):
        if part.strip() in _EXACT:
            return _EXACT[part.strip()]
    for kw, cat in _SUBSTR:
        if kw in s:
            return cat
    if any(tok in _US_TOKENS for tok in s.replace(",", " ").split()):
        return "us"
    return "other"
