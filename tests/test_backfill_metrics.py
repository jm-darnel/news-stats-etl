"""Tests for backfill aggregation + history export."""

from __future__ import annotations

import json

import duckdb
import pytest

from newsstats.backfill_metrics import build_outlet_daily, daily_totals, write_history_json


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE gdelt_article (article_id VARCHAR, outlet_id VARCHAR, domain VARCHAR, "
        "url VARCHAR, title VARCHAR, published_at TIMESTAMP, word_count INTEGER, author VARCHAR)"
    )
    rows = [
        ("a1", "cnn", "2022-01-01", 100),
        ("a2", "cnn", "2022-01-01", 200),
        ("a3", "cnn", "2022-01-02", 300),
        ("a4", "fox", "2022-01-01", 150),
    ]
    c.executemany(
        "INSERT INTO gdelt_article (article_id, outlet_id, published_at, word_count) "
        "VALUES (?, ?, CAST(? AS TIMESTAMP), ?)",
        rows,
    )
    return c


def test_daily_totals(conn):
    rows = daily_totals(conn)
    assert [(r["day"].isoformat(), r["articles"], r["avg_words"]) for r in rows] == [
        ("2022-01-01", 3, 150.0),
        ("2022-01-02", 1, 300.0),
    ]


def test_build_outlet_daily(conn):
    build_outlet_daily(conn)
    got = [(r[0], str(r[1]), r[2], r[3]) for r in conn.execute(
        "SELECT outlet_id, day, article_count, avg_word_count "
        "FROM gdelt_outlet_daily ORDER BY outlet_id, day"
    ).fetchall()]
    assert got == [
        ("cnn", "2022-01-01", 2, 150.0),
        ("cnn", "2022-01-02", 1, 300.0),
        ("fox", "2022-01-01", 1, 150.0),
    ]


def test_write_history_json(conn, tmp_path):
    out = tmp_path / "history"
    summary = write_history_json(conn, out)
    assert summary == {"articles": 4, "outlets": 2, "start": "2022-01-01", "end": "2022-01-02"}

    data = json.loads((out / "history.json").read_text())
    assert data["days"] == ["2022-01-01", "2022-01-02"]
    assert data["articles"] == [3, 1]
    assert data["avg_words"] == [150.0, 300.0]
    assert data["by_outlet"]["cnn"]["articles"] == [2, 1]
