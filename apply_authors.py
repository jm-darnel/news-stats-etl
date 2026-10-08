"""Apply author resolution to the warehouses (one-time M7 step).

1. Delete pseudo-authors from the FORWARD warehouse (MotherDuck) — the
   "Guardian staff reporter" / "Via AP news wire" / numeric-IDs that slipped in
   before the non-person filter was complete.
2. Build the BACKFILL canonical author leaderboard (raw PAGE_AUTHORS ->
   canonical names) and persist it locally + sync an aggregate to MotherDuck.
"""

from __future__ import annotations

import os
from collections import Counter

import duckdb

from newsstats.author_resolution import canonical_key, is_pseudo, split_names


def _chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def clean_forward(md) -> int:
    rows = md.execute("SELECT author_id, canonical_name FROM author").fetchall()
    pseudo = [r[0] for r in rows if is_pseudo(r[1])]
    for batch in _chunks(pseudo, 500):
        ph = ",".join("?" * len(batch))
        md.execute(f"DELETE FROM article_author WHERE author_id IN ({ph})", batch)
        md.execute(f"DELETE FROM author WHERE author_id IN ({ph})", batch)
    return len(pseudo)


def _display(name: str) -> str:
    return name.title() if name.isupper() else name


def build_backfill(gd) -> dict:
    raw_counts = gd.execute(
        "SELECT author, count(*) FROM gdelt_article WHERE author IS NOT NULL GROUP BY author"
    ).fetchall()
    canon: Counter = Counter()
    display: dict[str, str] = {}
    for raw, cnt in raw_counts:
        for n in split_names(raw):
            k = canonical_key(n)
            canon[k] += cnt
            display.setdefault(k, _display(n))

    gd.execute(
        "CREATE OR REPLACE TABLE gdelt_author "
        "(canonical_key VARCHAR, canonical_name VARCHAR, article_count BIGINT)"
    )
    gd.executemany(
        "INSERT INTO gdelt_author VALUES (?, ?, ?)",
        [(k, display[k], c) for k, c in canon.items()],
    )
    return {"canonical_authors": len(canon), "raw_byline_groups": len(raw_counts)}


def _load_env(path=".env"):
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    _load_env()
    md = duckdb.connect("md:newsstats")
    removed = clean_forward(md)
    print(f"forward: removed {removed} pseudo-authors")
    md.close()

    gd = duckdb.connect("data/gdelt_backfill.duckdb")
    stats = build_backfill(gd)
    print(f"backfill: {stats['raw_byline_groups']} raw bylines -> "
          f"{stats['canonical_authors']} canonical authors (gdelt_author table)")
    top = gd.execute(
        "SELECT canonical_name, article_count FROM gdelt_author "
        "ORDER BY article_count DESC LIMIT 10").fetchall()
    print("top authors:")
    for name, cnt in top:
        print(f"  {cnt:>7}  {name}")
    gd.close()


if __name__ == "__main__":
    main()
