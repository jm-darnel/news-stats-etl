"""Data-quality checks. Pure functions over canonical rows + per-source stats.

Returns DqResult records; nothing here touches the database. Wired into the ETL
by etl.py, which persists them to `dq_result` and counts failures into
`ingest_run.rows_flagged`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from newsstats.models import COMPLETENESS_FULL, CanonicalArticle, SourceConfig

MAX_WORD_COUNT = 20_000


@dataclass(frozen=True)
class DqResult:
    check_name: str
    passed: bool
    detail: str


def _is_future(value: str | None, now: datetime, skew: timedelta) -> bool:
    if not value:
        return False
    s = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return False  # unparseable dates are a different concern; not "future"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt > now + skew


def run_checks(
    source: SourceConfig,
    rows: list[CanonicalArticle],
    n_discovered: int,
    now: datetime | None = None,
) -> list[DqResult]:
    now = now or datetime.now(UTC)
    skew = timedelta(hours=1)  # tolerate small clock skew / ambiguous zones
    out: list[DqResult] = []

    out.append(DqResult("freshness", n_discovered > 0, f"{source.outlet_id}: {n_discovered} discovered"))

    if n_discovered > 0:
        out.append(
            DqResult(
                "extraction_yield",
                len(rows) > 0,
                f"{source.outlet_id}: {len(rows)}/{n_discovered} extracted",
            )
        )

    nulls = sum(
        1
        for r in rows
        if not all(
            [
                r.article_id,
                r.outlet_id,
                r.url,
                r.word_count_source,
                r.metric_completeness,
                r.source_type,
                r.first_seen_at,
            ]
        )
    )
    out.append(DqResult("null_required_keys", nulls == 0, f"{nulls} rows missing required keys"))

    bad_wc = sum(
        1
        for r in rows
        if r.metric_completeness == COMPLETENESS_FULL
        and (r.word_count is None or r.word_count < 1 or r.word_count > MAX_WORD_COUNT)
    )
    out.append(
        DqResult("word_count_bounds", bad_wc == 0, f"{bad_wc} full rows out of [1, {MAX_WORD_COUNT}]")
    )

    future = sum(
        1
        for r in rows
        if _is_future(r.published_at, now, skew) or _is_future(r.first_seen_at, now, skew)
    )
    out.append(DqResult("future_dates", future == 0, f"{future} rows with future dates"))

    ids = [r.article_id for r in rows]
    dups = len(ids) - len(set(ids))
    out.append(DqResult("duplicate_ids", dups == 0, f"{dups} duplicate article_ids"))

    return out
