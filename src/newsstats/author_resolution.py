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
    r"(?:^|\s+)for\s+(?:the\s+)?(mailonline|dailymail\.com|daily\s+mail(?:\s+australia)?"
    r"|mail\s+on\s+sunday|the\s+conversation|guardian|the\s+guardian|sun|the\s+sun"
    r"|cnn|nbc\s+news|fox\s+news|cbs\s+news|mail)", re.I)

_HTML_TAG = re.compile(r"<[^>]+>")

_NUMERIC = re.compile(r"^[\d\s\-]+$")
_BARE_HANDLE = re.compile(r"^[a-z0-9_]{2,24}$")  # a lone lowercase token = username

# desk/topic + role title ("showbusiness reporter", "health editor") = not a person
_ROLE_ONLY = re.compile(
    r"^[a-z]+[- ](reporter|editor|columnist|correspondent|critic|journalist|writer|reviewer"
    r"|photographer)s?$")

# Anything ending in a role title is (at least partly) a desk byline. Covers the
# archive-side leak GDELT exposes ("US NEWS REPORTER", "DAILY MAIL REPORTER") that
# the two-token _ROLE_ONLY misses. BUT a role tail can ride along on a real
# person's byline ("MARK NICOL DIPLOMACY EDITOR", "Xantha Leatham Science
# Correspondent"), so is_pseudo/clean_name strip the tail and keep the person.
# MailOnline appends a dateline AFTER the role ("Senior U.S. Political Reporter
# In Washington"), so the role match tolerates a trailing prepositional phrase.
_DESK_ROLE = re.compile(
    r"\b(reporters?|editors?|columnists?|correspondents?|critics?|journalists?|writers?"
    r"|reviewers?|photographers?)(\s+(?:in|at|on|for|of|aboard|with)\b.*)?\s*$", re.I)

# seniority/topic words that may sit between the person (or nothing) and the role
_ROLE_DESC = frozenset({
    "senior", "assistant", "associate", "chief", "deputy", "executive", "managing",
    "us", "usa", "foreign", "political", "diplomacy", "diplomatic", "science",
    "lifestyle", "money", "showbusiness", "showbiz", "sport", "sports", "city",
    "health", "crime", "media", "tech", "technology", "business", "football",
    "influencer", "news", "congressional",
})


def _person_part(name: str) -> str:
    """Strip a trailing role tail ('MARK NICOL DIPLOMACY EDITOR' -> 'MARK NICOL').

    Also strips a trailing dateline phrase ('U.S. POLITICAL REPORTER IN WASHINGTON'
    -> 'U.S. POLITICAL'). Returns '' when there is no person left ('ASSOCIATE
    SHOWBUSINESS EDITOR', 'SENIOR U.S. POLITICAL REPORTER').
    """
    m = _DESK_ROLE.search(name)
    if not m:
        return name.strip()
    person = name[: m.start()].strip()
    tokens = person.split()
    while tokens and tokens[-1].lower().replace(".", "").strip(".,;:-") in _ROLE_DESC:
        tokens.pop()
    return " ".join(tokens).strip(" .,;:-")

# sponsored-content / press-release labels
_LABEL_WORDS = (
    "advertis", "sponsored", "promoted content", "in association", "paid content",
    "brand content", "content from", "content by", "press release", "promotion",
)


def clean_name(name: str) -> str:
    n = html.unescape(name or "")
    n = _HTML_TAG.sub(" ", n)  # CNN bylines render as <a href="...">Name</a>
    n = _FOR_SUFFIX.sub("", n)
    n = re.sub(r"\s+", " ", n)
    n = n.strip(" \t\r\n.;:,")
    # bylines that end in a role title keep only the person: "MARK NICOL
    # DIPLOMACY EDITOR" -> "MARK NICOL"; pure desks reduce to '' (dropped)
    person = _person_part(n)
    return person.strip(" \t\r\n.;:,")


def _is_pseudo_core(name: str) -> bool:
    """is_pseudo without the role-tail handling (operates on the person part)."""
    if not name:
        return True
    if _NUMERIC.match(name) or _BARE_HANDLE.match(name):
        return True
    low = canonical_key(name)
    if low in _NON_PERSON or low.removeprefix("the ") in _NON_PERSON:
        return True
    if any(w in low for w in _LABEL_WORDS):
        return True
    if _ROLE_ONLY.match(low):
        return True
    if " " not in name and name.isupper() and len(name) > 1:  # "AUSTRALIA", "DAILY"
        return True
    return False


def is_pseudo(name: str) -> bool:
    """True if the token is an outlet/wire/role/garbage, not a person."""
    if _DESK_ROLE.search(name or ""):
        person = _person_part(name)
        # no person behind the role tail ("US NEWS REPORTER") -> desk
        return not person or _is_pseudo_core(person)
    return _is_pseudo_core(name)


def canonical_key(name: str) -> str:
    """Accent-fold + casefold key for cross-article dedup ('Kottasová' == 'kottasova')."""
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", n).strip().casefold()


_WIRE_STRIP = re.compile(
    r"\s*/\s*(?:ap|reuters|afp|upi|pa\s*media|xinhua|bloomberg|associated\s+press)\b.*$",
    re.I,
)


def split_names(raw: str | None) -> list[str]:
    """Raw byline -> deduplicated list of clean person names (preserving order)."""
    if not raw:
        return []
    s = _HTML_TAG.sub(" ", html.unescape(raw))
    # strip a trailing "/ WIRE ..." attribution ("Aamer Madhani / AP" -> "Aamer Madhani")
    s = _WIRE_STRIP.sub("", s)
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
