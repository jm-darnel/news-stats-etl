"""Export mart views to static JSON files for the dashboard.

The dashboard is plain HTML/JS + Chart.js, fetched from static JSON (no live
DB at request time). This module reads the marts and writes the chart data,
plus an ETL health line and rule-based trend insights (7/30/90 days).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _health(conn) -> dict:
    run = conn.execute(
        "SELECT run_id, finished_at, rows_in, rows_flagged, status "
        "FROM ingest_run ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return {"status": "error", "last_run_at": None, "text": "No ETL runs recorded."}

    run_id, finished, rows_in, flagged, status = run
    fails = conn.execute(
        "SELECT count(*) FROM dq_result WHERE run_id = ? AND passed = FALSE", [run_id]
    ).fetchone()[0]
    sources = conn.execute("SELECT count(*) FROM outlet").fetchone()[0]
    total = conn.execute("SELECT count(*) FROM article").fetchone()[0]

    age_h = (datetime.now(timezone.utc).replace(tzinfo=None) - finished).total_seconds() / 3600
    if status != "ok" or age_h > 24:
        tone = "error"
    elif flagged > 0 or fails > 0:
        tone = "warn"
    else:
        tone = "ok"

    return {
        "status": tone,
        "last_run_at": finished.isoformat(sep=" "),
        "age_hours": round(age_h, 1),
        "rows_last_run": rows_in,
        "rows_flagged": flagged,
        "dq_checks_failed": fails,
        "sources": sources,
        "total_articles": total,
    }


def _trends(conn) -> dict:
    """Rule-based window-vs-prior-window deltas for 7/30/90 days (5-year backfill)."""
    out = {}
    for w in (7, 30, 90):
        cur = conn.execute(
            "SELECT coalesce(sum(article_count),0), "
            "round(sum(article_count * avg_word_count)::DOUBLE / nullif(sum(article_count), 0), 1) "
            "FROM backfill_daily WHERE day >= current_date - (? * INTERVAL '1 DAY')",
            [w],
        ).fetchone()
        prev = conn.execute(
            "SELECT coalesce(sum(article_count),0) FROM backfill_daily "
            "WHERE day >= current_date - (? * INTERVAL '1 DAY') "
            "AND day < current_date - (? * INTERVAL '1 DAY')",
            [2 * w, w],
        ).fetchone()
        top = conn.execute(
            "SELECT outlet_id FROM backfill_outlet_daily "
            "WHERE day >= current_date - (? * INTERVAL '1 DAY') "
            "GROUP BY outlet_id ORDER BY sum(article_count) DESC LIMIT 1",
            [w],
        ).fetchone()

        vol, length = cur[0], cur[1]
        vol_prev = prev[0]
        delta = round((vol - vol_prev) / vol_prev * 100, 1) if vol_prev >= 50 else None
        out[str(w)] = {
            "articles": vol,
            "avg_words": length,
            "volume_pct_change": delta,
            "top_outlet": top[0] if top else None,
        }
    return out


def export_dashboard(conn, out_dir: str | Path = "dashboard") -> dict:
    data_dir = Path(out_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # full forward series (client applies date filters)
    vol = conn.execute(
        """
        SELECT day,
               sum(article_count) AS c,
               round(sum(total_words)::DOUBLE / sum(article_count), 1) AS avg_len
        FROM agg_outlet_daily
        GROUP BY day
        ORDER BY day
        """
    ).fetchall()
    days = [str(r[0]) for r in vol]
    volumes = [int(r[1]) for r in vol]
    avg_lens = [float(r[2]) for r in vol]

    leaderboard = conn.execute(
        """
        SELECT canonical_name, outlet_id, articles_30d, words_30d
        FROM agg_author_rolling
        WHERE words_30d > 0
        ORDER BY words_30d DESC
        LIMIT 20
        """
    ).fetchall()

    outlet_len = conn.execute(
        "SELECT outlet_id, article_count, avg_word_count "
        "FROM dim_outlet ORDER BY avg_word_count DESC"
    ).fetchall()

    payloads = {
        "summary": {
            "articles": conn.execute("SELECT count(*) FROM article").fetchone()[0],
            "authors": conn.execute("SELECT count(*) FROM author").fetchone()[0],
            "outlets": conn.execute("SELECT count(*) FROM outlet").fetchone()[0],
            "health": _health(conn),
            "trends": _trends(conn),
        },
        "volume": {"days": days, "total": volumes},
        "length": {"days": days, "avg": avg_lens},
        "leaderboard": [
            {"author": r[0], "outlet": r[1], "articles": int(r[2]), "words": int(r[3])}
            for r in leaderboard
        ],
        "outlet_length": [
            {"outlet": r[0], "count": int(r[1]), "avg": float(r[2])}
            for r in outlet_len
        ],
    }
    for name, data in payloads.items():
        (data_dir / f"{name}.json").write_text(json.dumps(data, indent=2))
    return payloads["summary"]