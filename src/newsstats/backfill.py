"""GDELT GKG historical backfill.

Stream GDELT's 15-minute Global Knowledge Graph files (free, back to Feb 2015),
keep only records whose source domain is one of our registered outlets, and
extract per-article (url, publish date, word count, author, title). The GKG
carries everything the backfill needs, so no CC-NEWS / WARC processing.

Design constraints:
- Resumable: the caller tracks which file timestamps are done; ids are stable.
- Throttlable: the caller paces downloads (politeness + home bandwidth).
- Local: heavy compute stays in a local DuckDB file; MotherDuck gets aggregates.
"""

from __future__ import annotations

import csv
import io
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib import request

from .models import article_id_for

# Some GKG rows carry single fields (counts/locations/extras) far bigger than
# Python's 128 KB csv default; raise it or the whole file fails to parse.
csv.field_size_limit(sys.maxsize)

GKG_BASE = "https://data.gdeltproject.org/gdeltv2"

_WC = re.compile(r"(?:^|,)wc:(\d+)")
_AUTHORS = re.compile(r"<PAGE_AUTHORS>(.*?)</PAGE_AUTHORS>", re.S)
_PUBLISHED = re.compile(r"<PAGE_PRECISEPUBTIMESTAMP>(\d+)</PAGE_PRECISEPUBTIMESTAMP>")
_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)

# GKG is 27 tab-separated columns; indexes for the fields we keep.
_COL_DATE = 1
_COL_DOMAIN = 3
_COL_URL = 4
_COL_COUNTS = 17
_COL_EXTRAS = 26


def gkg_timestamps(start: datetime, end: datetime) -> list[str]:
    """15-minute YYYYMMDDHHMMSS timestamps in [start, end)."""
    out: list[str] = []
    cur = start.replace(minute=start.minute - start.minute % 15, second=0, microsecond=0)
    while cur < end:
        out.append(cur.strftime("%Y%m%d%H%M%S"))
        cur += timedelta(minutes=15)
    return out


@dataclass
class GkgRecord:
    outlet_id: str
    domain: str
    url: str
    article_id: str
    title: str | None
    published_at: str | None  # ISO "YYYY-MM-DD HH:MM:SS"
    word_count: int | None
    author: str | None


def match_outlet(domain: str, domain_map: dict[str, str]) -> str | None:
    d = (domain or "").strip().lower().lstrip(".")
    if d in domain_map:
        return domain_map[d]
    for dom, oid in domain_map.items():
        if d.endswith("." + dom):
            return oid
    return None


def _ts_to_iso(ts: str) -> str | None:
    try:
        return datetime.strptime(ts, "%Y%m%d%H%M%S").isoformat(sep=" ")
    except (ValueError, TypeError):
        return None


def parse_row(row: list[str], domain_map: dict[str, str]) -> GkgRecord | None:
    """Map one raw GKG row to a GkgRecord, or None if not ours / malformed."""
    if len(row) < 27:
        return None
    oid = match_outlet(row[_COL_DOMAIN], domain_map)
    if oid is None:
        return None
    url = (row[_COL_URL] or "").strip()
    if not url:
        return None

    counts = row[_COL_COUNTS] or ""
    m = _WC.search(counts)
    word_count = int(m.group(1)) if m else None

    extras = row[_COL_EXTRAS] or ""
    author = _AUTHORS.search(extras)
    author = author.group(1).strip() if author else None
    title = _TITLE.search(extras)
    title = title.group(1).strip() if title else None
    pub = _PUBLISHED.search(extras)
    pub_ts = pub.group(1) if pub else (row[_COL_DATE] if len(row) > _COL_DATE else None)
    published_at = _ts_to_iso(pub_ts) if pub_ts else None

    return GkgRecord(
        outlet_id=oid,
        domain=(row[_COL_DOMAIN] or "").strip().lower(),
        url=url,
        article_id=article_id_for(url),
        title=title,
        published_at=published_at,
        word_count=word_count,
        author=author,
    )


def fetch_file(url: str, retries: int = 3) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = request.Request(url, headers={"User-Agent": "news-stats-etl/0.1 (portfolio)"})
            with request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last_exc = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed after {retries} attempts") from last_exc


def iter_rows(data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
                                delimiter="\t")
            yield from reader


def throttle(n_bytes: int, max_mbps: float, t0: float) -> None:
    target = n_bytes / (max_mbps * 1e6 / 8)
    elapsed = time.time() - t0
    if elapsed < target:
        time.sleep(target - elapsed)


# Row tuple matching the CLI's INSERT column order.
def process_gkg_file(ts: str, domain_map: dict[str, str],
                     base: str = GKG_BASE, per_worker_mbps: float | None = None) -> list[tuple]:
    """Download, decompress, parse, and filter one 15-min GKG file.

    Runs in a worker process; returns only matching rows as tuples (no DB here,
    so DuckDB keeps a single writer in the parent).
    """
    t0 = time.time()
    data = fetch_file(f"{base}/{ts}.gkg.csv.zip")
    if per_worker_mbps:
        throttle(len(data), per_worker_mbps, t0)
    out: list[tuple] = []
    for row in iter_rows(data):
        try:
            rec = parse_row(row, domain_map)
        except Exception:  # noqa: BLE001
            continue  # one malformed row must not sink the whole file
        if rec is not None:
            out.append((rec.article_id, rec.outlet_id, rec.domain, rec.url,
                        rec.title, rec.published_at, rec.word_count, rec.author))
    return out
