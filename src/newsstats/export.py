"""Export mart views to static JSON files for the dashboard.

The dashboard is plain HTML/JS + Chart.js, fetched from static JSON (no live
DB at request time). This module reads the marts and writes the chart data.
"""

from __future__ import annotations

import json
from pathlib import Path


def export_dashboard(conn, out_dir: str | Path = "dashboard") -> dict:
    data_dir = Path(out_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    vol = conn.execute(
        """
        SELECT day,
               sum(article_count) AS c,
               round(sum(total_words)::DOUBLE / sum(article_count), 1) AS avg_len
        FROM agg_outlet_daily
        WHERE day >= current_date - INTERVAL 90 DAY
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
        """
        SELECT outlet_id, article_count, avg_word_count
        FROM dim_outlet
        ORDER BY avg_word_count DESC
        """
    ).fetchall()

    payloads = {
        "summary": {
            "articles": conn.execute("SELECT count(*) FROM article").fetchone()[0],
            "authors": conn.execute("SELECT count(*) FROM author").fetchone()[0],
            "outlets": conn.execute("SELECT count(*) FROM outlet").fetchone()[0],
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
