"""GDELT GKG backfill CLI.

Usage:
  python backfill.py --slice 96          # validate: 1 day of files
  python backfill.py                      # full 5-year run (resumable)
  python backfill.py --start 2021-10-01 --max-mbps 50

Streams GDELT 15-min GKG files, keeps the 22 source domains, and appends
per-article (url, date, word count, author, title) to a local DuckDB file.
Tracks completed timestamps so the run resumes where it left off.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time
import zipfile
from datetime import datetime, timedelta
from urllib import request

import duckdb

from newsstats.backfill import GKG_BASE, gkg_timestamps, parse_row
from newsstats.config import load_sources

_DDL = """
CREATE TABLE IF NOT EXISTS gdelt_article (
    article_id VARCHAR PRIMARY KEY,
    outlet_id VARCHAR,
    domain VARCHAR,
    url VARCHAR,
    title VARCHAR,
    published_at TIMESTAMP,
    word_count INTEGER,
    author VARCHAR,
    word_count_source VARCHAR,
    source_type VARCHAR
);
CREATE TABLE IF NOT EXISTS gdelt_files_done (ts VARCHAR PRIMARY KEY);
"""

_SQL_INSERT = """
INSERT OR IGNORE INTO gdelt_article
  (article_id, outlet_id, domain, url, title, published_at, word_count,
   author, word_count_source, source_type)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'gdelt', 'gdelt_backfill')
"""


def _fetch(url: str, retries: int = 3) -> bytes:
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


def _iter_rows(data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
                                delimiter="\t")
            yield from reader


def _throttle(n_bytes: int, max_mbps: float, t0: float) -> None:
    target = n_bytes / (max_mbps * 1e6 / 8)
    elapsed = time.time() - t0
    if elapsed < target:
        time.sleep(target - elapsed)


def main() -> None:
    ap = argparse.ArgumentParser(description="GDELT GKG 5-year backfill")
    ap.add_argument("--start", default="2021-10-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--db", default="data/gdelt_backfill.duckdb")
    ap.add_argument("--slice", type=int, default=0, help="process only the first N files")
    ap.add_argument("--max-mbps", type=float, default=50.0, help="download throttle")
    ap.add_argument("--log-every", type=int, default=96, help="print progress every N files")
    args = ap.parse_args()

    domain_map = {s.domain: s.outlet_id for s in load_sources()}
    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d") if args.end else datetime.now()
    if args.end is None:
        end = end + timedelta(days=1)  # inclusive of today
    stamps = gkg_timestamps(start, end)
    if args.slice:
        stamps = stamps[: args.slice]
    print(f"outlets={len(domain_map)}  files={len(stamps)}  "
          f"window={start.date()}..{end.date()}")

    conn = duckdb.connect(args.db)
    conn.execute(_DDL)
    done = {r[0] for r in conn.execute("SELECT ts FROM gdelt_files_done").fetchall()}
    todo = [s for s in stamps if s not in done]
    print(f"resuming: {len(done)} done, {len(todo)} to process")

    kept = 0
    processed = 0
    try:
        for i, ts in enumerate(todo):
            t0 = time.time()
            data = _fetch(f"{GKG_BASE}/{ts}.gkg.csv.zip")
            _throttle(len(data), args.max_mbps, t0)

            batch = []
            for row in _iter_rows(data):
                rec = parse_row(row, domain_map)
                if rec is not None:
                    batch.append((rec.article_id, rec.outlet_id, rec.domain, rec.url,
                                  rec.title, rec.published_at, rec.word_count, rec.author))
            if batch:
                conn.executemany(_SQL_INSERT, batch)
                kept += len(batch)
            conn.execute("INSERT OR IGNORE INTO gdelt_files_done VALUES (?)", [ts])
            processed += 1

            if (i + 1) % args.log_every == 0:
                conn.commit()
                print(f"  {i + 1}/{len(todo)} files  kept={kept}  "
                      f"last={ts}  elapsed={time.time() - t0:.1f}s", flush=True)
    finally:
        conn.commit()
    conn.close()
    print(f"done. processed={processed} files, kept={kept} rows -> {args.db}")


if __name__ == "__main__":
    sys.exit(main())
