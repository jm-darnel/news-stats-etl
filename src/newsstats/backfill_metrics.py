"""Aggregate and serve the GDELT backfill.

gdelt_article (per-article rows) -> daily series per outlet -> the 5-year
dashboard history JSON. Reconciliation vs forward data is done separately at
the end (one-off query over both warehouses).
"""

from __future__ import annotations

import json
from pathlib import Path

# The backfill streamed GDELT files from 2021-10-01. GDELT's <PAGE_PRECISEPUBTIMESTAMP>
# is occasionally garbage (dates back to 1979); anything before the window start is
# miscategorized and excluded from aggregates.
WINDOW_START = "2021-10-01"


def build_outlet_daily(conn) -> None:
    """Create gdelt_outlet_daily: one row per (outlet, day)."""
    conn.execute(
        """
        CREATE OR REPLACE TABLE gdelt_outlet_daily AS
        SELECT outlet_id,
               CAST(published_at AS DATE) AS day,
               count(*) AS article_count,
               round(avg(word_count), 1) AS avg_word_count
        FROM gdelt_article
        WHERE published_at >= CAST(? AS TIMESTAMP)
        GROUP BY outlet_id, CAST(published_at AS DATE)
        """,
        [WINDOW_START],
    )


def daily_totals(conn) -> list[dict]:
    """Total articles + mean length per day (headline 5-year series)."""
    return [dict(zip(("day", "articles", "avg_words"), r, strict=False)) for r in conn.execute(
        """
        SELECT CAST(published_at AS DATE) AS day,
               count(*) AS articles,
               round(avg(word_count), 1) AS avg_words
        FROM gdelt_article
        WHERE published_at >= CAST(? AS TIMESTAMP)
        GROUP BY CAST(published_at AS DATE)
        ORDER BY day
        """,
        [WINDOW_START],
    ).fetchall()]


def write_history_json(conn, out_dir: str | Path = "dashboard/data") -> dict:
    """Write dashboard/data/history.json with the 5-year daily series."""
    data_dir = Path(out_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    build_outlet_daily(conn)
    totals = daily_totals(conn)

    by_outlet = {}
    for r in conn.execute(
        "SELECT outlet_id, CAST(day AS VARCHAR) AS day, article_count "
        "FROM gdelt_outlet_daily ORDER BY outlet_id, day"
    ).fetchall():
        by_outlet.setdefault(r[0], {"days": [], "articles": []})
        by_outlet[r[0]]["days"].append(r[1])
        by_outlet[r[0]]["articles"].append(r[2])

    payload = {
        "summary": {
            "articles": conn.execute(
                "SELECT count(*) FROM gdelt_article WHERE published_at >= CAST(? AS TIMESTAMP)",
                [WINDOW_START],
            ).fetchone()[0],
            "outlets": conn.execute(
                "SELECT count(DISTINCT outlet_id) FROM gdelt_article "
                "WHERE published_at >= CAST(? AS TIMESTAMP)",
                [WINDOW_START],
            ).fetchone()[0],
            "start": totals[0]["day"].isoformat() if totals else None,
            "end": totals[-1]["day"].isoformat() if totals else None,
        },
        "days": [r["day"].isoformat() for r in totals],
        "articles": [r["articles"] for r in totals],
        "avg_words": [r["avg_words"] for r in totals],
        "by_outlet": by_outlet,
    }
    (data_dir / "history.json").write_text(json.dumps(payload))
    return payload["summary"]
