"""Constrained natural-language metric query engine for the chatbot.

The chatbot never emits free SQL. A question is parsed (by an LLM, or a
deterministic rule fallback) into a small `MetricQuery` schema, validated
against a whitelist of metrics/dimensions/outlets/categories, and compiled to
parameterized SQL. This keeps answers deterministic, safe from injection, and
testable without a live model.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

METRICS = ("articles", "avg_words", "total_words")
DIMENSIONS = ("outlet", "author", "category", "day")

_METRIC_SQL = {
    "articles": "COUNT(*)",
    "avg_words": "ROUND(AVG(a.word_count), 1)",
    "total_words": "SUM(a.word_count)",
}
_METRIC_LABEL = {
    "articles": "articles",
    "avg_words": "avg length (words)",
    "total_words": "words",
}


class QueryError(ValueError):
    """A question could not be mapped onto the constrained metric model."""


@dataclass
class MetricQuery:
    metrics: list[str] = field(default_factory=lambda: ["articles"])
    dimension: str | None = None
    outlets: list[str] = field(default_factory=list)
    category: str | None = None
    author: str | None = None
    start: str | None = None  # ISO date, inclusive
    end: str | None = None    # ISO date, inclusive
    days: int | None = None   # relative: last N days
    limit: int = 20

    def validate(self, valid_outlets: set[str] | None = None,
                 valid_categories: set[str] | None = None) -> MetricQuery:
        if not self.metrics:
            raise QueryError("no metrics requested")
        bad = [m for m in self.metrics if m not in METRICS]
        if bad:
            raise QueryError(f"unknown metric(s): {bad}")
        if self.dimension is not None and self.dimension not in DIMENSIONS:
            raise QueryError(f"unknown dimension: {self.dimension}")
        if valid_outlets is not None:
            bad = [o for o in self.outlets if o not in valid_outlets]
            if bad:
                raise QueryError(f"unknown outlet(s): {bad}")
        if valid_categories is not None and self.category is not None:
            if self.category not in valid_categories:
                raise QueryError(f"unknown category: {self.category}")
        if self.days is not None and self.days <= 0:
            raise QueryError("days must be positive")
        self.limit = max(1, min(int(self.limit or 20), 100))
        return self


def build_sql(q: MetricQuery) -> tuple[str, list[Any]]:
    params: list[Any] = []
    needs_author = q.dimension == "author" or q.author is not None

    if needs_author:
        from_sql = (
            "FROM article a "
            "JOIN article_author aa ON a.article_id = aa.article_id "
            "JOIN author au ON aa.author_id = au.author_id"
        )
    else:
        from_sql = "FROM article a"

    select = [f"{_METRIC_SQL[m]} AS {m}" for m in q.metrics]
    group_by = ""
    order = ""
    if q.dimension == "outlet":
        select.insert(0, "a.outlet_id AS key")
        group_by = "GROUP BY a.outlet_id"
        order = f"ORDER BY {q.metrics[0]} DESC"
    elif q.dimension == "category":
        select.insert(0, "COALESCE(a.category, 'other') AS key")
        group_by = "GROUP BY a.category"
        order = f"ORDER BY {q.metrics[0]} DESC"
    elif q.dimension == "author":
        select.insert(0, "au.canonical_name AS key")
        select.insert(1, "a.outlet_id AS outlet_id")
        group_by = "GROUP BY au.canonical_name, a.outlet_id"
        order = f"ORDER BY {q.metrics[0]} DESC"
    elif q.dimension == "day":
        select.insert(0, "CAST(a.published_at AS DATE) AS key")
        group_by = "GROUP BY CAST(a.published_at AS DATE)"
        order = "ORDER BY key"

    where = ["a.published_at IS NOT NULL"]
    if q.outlets:
        ph = ", ".join("?" for _ in q.outlets)
        where.append(f"a.outlet_id IN ({ph})")
        params.extend(q.outlets)
    if q.category:
        where.append("a.category = ?")
        params.append(q.category)
    if q.author:
        where.append("au.canonical_name ILIKE ?")
        params.append(f"%{q.author}%")
    if q.start:
        where.append("a.published_at >= CAST(? AS TIMESTAMP)")
        params.append(q.start)
    if q.end:
        where.append("a.published_at < CAST(? AS TIMESTAMP) + INTERVAL 1 DAY")
        params.append(q.end)
    if q.days and not (q.start or q.end):
        where.append("a.published_at >= CAST(current_date AS TIMESTAMP) - (? * INTERVAL '1 DAY')")
        params.append(q.days)

    sql = f"SELECT {', '.join(select)} {from_sql} WHERE {' AND '.join(where)}"
    if group_by:
        sql += f" {group_by} {order}"
    sql += f" LIMIT {q.limit}"
    return sql, params


def run_query(conn, q: MetricQuery) -> list[dict]:
    sql, params = build_sql(q)
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def _fmt(v) -> str:
    if v is None:
        return "0"
    if isinstance(v, float):
        return f"{v:,.1f}"
    return f"{v:,}"


def format_answer(q: MetricQuery, rows: list[dict]) -> str:
    if not rows or all(r.get(q.metrics[0]) in (0, None) for r in rows):
        return "No matching articles found for that window."

    if q.dimension is None:
        r = rows[0]
        parts = [f"{_fmt(r[m])} {_METRIC_LABEL[m]}" for m in q.metrics]
        return "Overall: " + ", ".join(parts) + "."

    lines = []
    for r in rows:
        key = r.get("key")
        if q.dimension == "day" and key is not None:
            key = str(key)
        elif q.dimension == "author":
            key = f"{key} ({r.get('outlet_id')})"
        metrics_str = ", ".join(f"{_fmt(r[m])} {_METRIC_LABEL[m]}" for m in q.metrics)
        lines.append(f"- **{key}**: {metrics_str}")

    intro = "Comparison:" if q.dimension == "outlet" and len(q.outlets) > 1 else "Breakdown:"
    return intro + "\n" + "\n".join(lines)


def answer(question: str, conn, llm_fn: Callable[[str], str] | None = None,
           valid_outlets: set[str] | None = None,
           valid_categories: set[str] | None = None) -> str:
    try:
        q = parse_question(question, llm_fn, valid_outlets, valid_categories)
        q.validate(valid_outlets, valid_categories)
        rows = run_query(conn, q)
        return format_answer(q, rows)
    except QueryError as e:
        return (f"I can't answer that with the metrics I track. ({e}) "
                "Try asking about article volume, average length, or total words, "
                "grouped by outlet, author, category, or day, over a date range.")


# ---------------------------------------------------------------------------
# Parsing: LLM first (if a callable is provided), else deterministic rules.
# ---------------------------------------------------------------------------

_PROMPT = """You convert a news-analytics question into a strict JSON query.

Allowed metrics: articles, avg_words, total_words.
Allowed dimension (group by, or null for overall totals): outlet, author, category, day.
Valid outlets (id): {outlets}
Valid categories: {categories}

Rules:
- Map outlet names to their ids from the valid list (e.g. "CNN" -> "cnn", "FOX News" -> "fox").
- metrics: which of articles/avg_words/total_words are asked for. "volume" -> articles,
  "length" -> avg_words. If asked for both, include both.
- dimension: "outlet" if comparing/by outlet, "author" for an author leaderboard or
  per-author stats, "category" by topic, "day" for a time series. null for a single total.
- outlets: list of outlet ids to restrict to (empty = all).
- category: a single valid category, or null.
- author: a name substring to match one author, or null.
- Date range: EITHER days (integer, "last N days") OR start+end (ISO YYYY-MM-DD, inclusive).
  Resolve relative dates against today's date ({today}). "final week of September 2025" ->
  start 2025-09-24, end 2025-09-30. "September 2025" -> start 2025-09-01, end 2025-09-30.
- limit: max rows (default 20).

Return ONLY valid JSON with keys: metrics, dimension, outlets, category, author, start, end, days, limit.
No prose, no code fences.

Question: {question}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise QueryError("LLM returned no JSON")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise QueryError(f"LLM returned invalid JSON: {e}") from e


def parse_question_llm(question: str, llm_fn: Callable[[str], str],
                       valid_outlets: set[str], valid_categories: set[str]) -> MetricQuery:
    from datetime import date
    prompt = _PROMPT.format(
        outlets=", ".join(sorted(valid_outlets)),
        categories=", ".join(sorted(valid_categories)),
        today=date.today().isoformat(),
        question=question,
    )
    data = _extract_json(llm_fn(prompt))
    return MetricQuery(
        metrics=[m for m in data.get("metrics", ["articles"]) if isinstance(m, str)],
        dimension=data.get("dimension") or None,
        outlets=[o for o in data.get("outlets", []) if isinstance(o, str)],
        category=data.get("category") or None,
        author=data.get("author") or None,
        start=data.get("start") or None,
        end=data.get("end") or None,
        days=data.get("days") or None,
        limit=data.get("limit") or 20,
    )


def parse_question_rules(question: str, valid_outlets: set[str],
                         valid_categories: set[str]) -> MetricQuery:
    """Deterministic fallback parser for common phrasings (no LLM needed)."""
    t = question.lower()
    q = MetricQuery()

    metrics: list[str] = []
    if any(w in t for w in ("volume", "how many", "count", "number of", "articles")):
        metrics.append("articles")
    if any(w in t for w in ("length", "long", "word count", "wordy")):
        metrics.append("avg_words")
    if "total words" in t or "total word" in t:
        metrics.append("total_words")
    q.metrics = list(dict.fromkeys(metrics)) or ["articles"]

    if "author" in t or "who" in t or "leaderboard" in t or "writer" in t:
        q.dimension = "author"
    elif "categor" in t or "topic" in t or "subject" in t:
        q.dimension = "category"
    elif "over time" in t or "trend" in t or "per day" in t or "each day" in t or "daily" in t:
        q.dimension = "day"
    elif "outlet" in t or "compare" in t or " vs " in t or "versus" in t or "between" in t:
        q.dimension = "outlet"

    # outlet name matching
    for oid in valid_outlets:
        if re.search(rf"\b{re.escape(oid)}\b", t):
            q.outlets.append(oid)
    # common aliases
    if re.search(r"\bfox\b|fox news", t) and "fox" in valid_outlets and "fox" not in q.outlets:
        q.outlets.append("fox")
    if len(q.outlets) > 1:
        q.dimension = "outlet"

    for c in valid_categories:
        if re.search(rf"\b{re.escape(c)}\b", t):
            q.category = c
            break

    m = re.search(r"(?:past|last)\s+(\d+)\s+days", t)
    if m:
        q.days = int(m.group(1))
    elif "week" in t and not (q.start or q.end):
        q.days = 7
    elif "month" in t and not (q.start or q.end):
        q.days = 30

    return q


def parse_question(question: str, llm_fn: Callable[[str], str] | None = None,
                   valid_outlets: set[str] | None = None,
                   valid_categories: set[str] | None = None) -> MetricQuery:
    outlets = valid_outlets or set()
    categories = valid_categories or set()
    if llm_fn is not None:
        return parse_question_llm(question, llm_fn, outlets, categories)
    return parse_question_rules(question, outlets, categories)


def load_whitelists(conn) -> tuple[set[str], set[str]]:
    outlets = {r[0] for r in conn.execute("SELECT outlet_id FROM outlet").fetchall()}
    cats = {r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM article WHERE category IS NOT NULL").fetchall()}
    return outlets, cats
