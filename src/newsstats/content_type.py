"""Content-type classification from per-outlet URL patterns.

Decision 2026-10-14: derived vs archive word-count averages diverge >=50% on 6
of 22 outlets. Root cause is content genre (listicles, deal roundups, guides)
that GDELT's `wc:` collapses to a quantized floor (multiples of 25), not a
derivation bug (live re-extraction reproduced derived counts exactly).

Genre is detected from URL structure, NOT a global pattern: the /list/ path is
an LA Times CMS convention (precision 0.98 there, recall 0.246 overall, and a
global title regex dropped to 0.60 precision with Guardian false positives).
So the pattern is per-outlet config in sources.yaml (`list_url_pattern`),
opt-in per outlet, and unvalidated outlets simply stay 'article'.
"""

from __future__ import annotations

import re
from functools import cache

from newsstats.models import SourceConfig

ARTICLE = "article"
LIST = "list"
LIVE_POST = "live_post"

CONTENT_TYPES = (ARTICLE, LIST, LIVE_POST)


@cache
def _compiled(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


def classify_content(url: str, source: SourceConfig) -> str:
    """Classify by the outlet's own URL pattern. Default is 'article'.

    Only outlets that opt in with `list_url_pattern` / `live_post_url_pattern`
    in sources.yaml can leave the default, so precision stays high (a global
    regex does not generalize across CMSes). Latched live-news posts on CNN and
    Fox are 'live_post': real GDELT documents, but a post inside a rolling live
    page, not an article. Idempotent and cheap: at most one regex per rule.
    """
    if source.list_url_pattern and _compiled(source.list_url_pattern).search(url):
        return LIST
    if source.live_post_url_pattern and _compiled(source.live_post_url_pattern).search(url):
        return LIVE_POST
    return ARTICLE
