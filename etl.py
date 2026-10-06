"""CLI entrypoint: discover -> fetch -> extract -> normalize -> load."""

from __future__ import annotations

import argparse
import os
import uuid
from datetime import UTC, datetime

from newsstats import discover, extract, fetch, load, normalize
from newsstats.config import get_source


def main() -> None:
    ap = argparse.ArgumentParser(description="newsstats ETL")
    ap.add_argument("--source", required=True, help="outlet_id from sources.yaml")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--db", default=None, help="DuckDB path or MotherDuck md: URL")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    source = get_source(args.source)
    conn = load.connect(args.db)
    load.init_schema(conn)
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC).isoformat()

    discovered = discover.discover(source, limit=args.limit)
    rows = []
    for d in discovered:
        try:
            html = fetch.fetch_html(d.url)
            ex = extract.extract_article(html, d.url)
            rows.append(normalize.to_canonical(d, ex, source, seen_at=started))
        except Exception as e:  # noqa: BLE001 - keep the run going, log the skip
            print(f"  skip {d.url}: {type(e).__name__}: {e}")

    if not args.dry_run and rows:
        load.upsert(conn, source, rows, run_id, started)

    for r in rows:
        cat = str(r.category)[:14]
        print(
            f"{r.outlet_id:14} wc={r.word_count:>6} conf={r.extraction_confidence:.2f} "
            f"cat={cat:14} authors={r.authors} title={r.title!r}"
        )
    target = args.db or os.environ.get("NEWSSTATS_DB_URL", load.DEFAULT_DB)
    print(f"\n{len(rows)} rows ingested (run {run_id[:8]}) into {target}")


if __name__ == "__main__":
    main()
