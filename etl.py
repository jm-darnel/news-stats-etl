"""CLI entrypoint: discover -> fetch -> extract -> normalize -> load.

With no --source, runs every source in sources.yaml. With --source <id>, runs one.
This is the scheduled forward ETL; --limit caps articles per source (default: full feed).
"""

from __future__ import annotations

import argparse
import os
import uuid
from datetime import UTC, datetime

from newsstats import discover, extract, fetch, load, normalize
from newsstats.config import get_source, load_sources


def run_source(conn, source, limit: int | None, dry_run: bool) -> int:
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC).isoformat()
    discovered = discover.discover(source, limit=limit)
    rows = []
    for d in discovered:
        try:
            html = fetch.fetch_html(d.url)
            ex = extract.extract_article(html, d.url)
            rows.append(normalize.to_canonical(d, ex, source, seen_at=started))
        except Exception as e:  # noqa: BLE001 - keep the run going, log the skip
            print(f"  skip {d.url}: {type(e).__name__}: {e}")
    if not dry_run and rows:
        load.upsert(conn, source, rows, run_id, started)
    for r in rows:
        cat = str(r.category)[:18]
        print(
            f"    {r.outlet_id:14} wc={r.word_count:>6} conf={r.extraction_confidence:.2f} "
            f"cat={cat:18} authors={r.authors}"
        )
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="newsstats ETL")
    ap.add_argument("--source", default=None, help="outlet_id from sources.yaml; omit to run all")
    ap.add_argument("--limit", type=int, default=None, help="cap articles per source")
    ap.add_argument("--db", default=None, help="DuckDB path or MotherDuck md: URL")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sources = load_sources() if args.source in (None, "all") else [get_source(args.source)]
    conn = load.connect(args.db)
    load.init_schema(conn)

    total = 0
    for source in sources:
        print(f"{source.outlet_id} ({source.discovery})")
        try:
            total += run_source(conn, source, args.limit, args.dry_run)
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {source.outlet_id}: {type(e).__name__}: {e}")

    target = args.db or os.environ.get("NEWSSTATS_DB_URL", load.DEFAULT_DB)
    print(f"\n{total} rows across {len(sources)} source(s) -> {target}")


if __name__ == "__main__":
    main()
