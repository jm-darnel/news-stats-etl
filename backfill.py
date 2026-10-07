"""GDELT GKG backfill CLI.

Usage:
  python backfill.py --slice 96             # validate: 1 day of files
  python backfill.py --workers 8            # full 5-year run (resumable)
  python backfill.py --start 2021-10-01 --max-mbps 200

Streams GDELT 15-min GKG files, keeps the 22 source domains, and appends
per-article (url, date, word count, author, title) to a local DuckDB file.
Download + parse run in worker processes (embarrassingly parallel); DuckDB
has a single writer in the parent. Tracks completed timestamps so the run
resumes where it left off.
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

import duckdb

from newsstats.backfill import GKG_BASE, gkg_timestamps, process_gkg_file
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


def main() -> None:
    ap = argparse.ArgumentParser(description="GDELT GKG 5-year backfill")
    ap.add_argument("--start", default="2021-10-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--db", default="data/gdelt_backfill.duckdb")
    ap.add_argument("--slice", type=int, default=0, help="process only the first N files")
    ap.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 4))
    ap.add_argument("--max-mbps", type=float, default=200.0, help="aggregate download throttle")
    ap.add_argument("--log-every", type=int, default=192, help="print progress every N files")
    args = ap.parse_args()

    domain_map = {s.domain: s.outlet_id for s in load_sources()}
    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d") if args.end else datetime.now()
    if args.end is None:
        end = end + timedelta(days=1)
    stamps = gkg_timestamps(start, end)
    if args.slice:
        stamps = stamps[: args.slice]

    conn = duckdb.connect(args.db)
    conn.execute(_DDL)
    done = {r[0] for r in conn.execute("SELECT ts FROM gdelt_files_done").fetchall()}
    todo = [s for s in stamps if s not in done]
    print(f"outlets={len(domain_map)}  files={len(stamps)}  "
          f"window={start.date()}..{end.date()}  workers={args.workers}")
    print(f"resuming: {len(done)} done, {len(todo)} to process")

    per_worker_mbps = args.max_mbps / args.workers if args.max_mbps else None
    kept = 0
    processed = 0
    failed = 0
    t_start = time.time()

    it = iter(todo)
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        while True:
            batch = list(itertools.islice(it, args.workers * 4))
            if not batch:
                break
            futs = {ex.submit(process_gkg_file, ts, domain_map, GKG_BASE,
                              per_worker_mbps): ts for ts in batch}
            for fut in as_completed(futs):
                ts = futs[fut]
                try:
                    rows = fut.result()
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"  FAILED {ts}: {e}", flush=True)
                    continue  # leave un-done so a later run retries it
                if rows:
                    conn.executemany(_SQL_INSERT, rows)
                    kept += len(rows)
                conn.execute("INSERT OR IGNORE INTO gdelt_files_done VALUES (?)", [ts])
                processed += 1
            conn.commit()
            rate = processed / max(1, time.time() - t_start)
            print(f"  {processed}/{len(todo)} files  kept={kept}  failed={failed}  "
                  f"~{rate:.1f} files/s", flush=True)

    conn.commit()
    conn.close()
    print(f"done. files={processed} kept={kept} rows failed={failed} -> {args.db}")


if __name__ == "__main__":
    sys.exit(main())
