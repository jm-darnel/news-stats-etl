"""Polite HTTP fetch. requests handles gzip content-encoding transparently."""

from __future__ import annotations

import time
from urllib.parse import urlsplit

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_session = requests.Session()
_last_hit: dict[str, float] = {}
POLITE_DELAY_S = 0.5


def fetch_url(url: str, timeout: int = 25, retries: int = 2) -> str:
    host = urlsplit(url).netloc
    wait = POLITE_DELAY_S - (time.monotonic() - _last_hit.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = _session.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            _last_hit[host] = time.monotonic()
            return r.text
        except requests.RequestException as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    assert last_err is not None
    raise last_err


def fetch_html(url: str, **kwargs) -> str:
    return fetch_url(url, **kwargs)
