"""Tests for the constrained metric-query chatbot.

The LLM parse is stubbed with canned JSON so the full pipeline (parse ->
validate -> SQL -> run -> format) is deterministic and checked against a known
fixture, including the two example questions from the project vision.
"""

from __future__ import annotations

import json

import duckdb
import pytest

from newsstats import chat
from newsstats.chat import MetricQuery, QueryError, answer, build_sql, run_query


def make_db():
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE outlet (outlet_id VARCHAR, name VARCHAR, domain VARCHAR, "
              "discovery VARCHAR, feed_url VARCHAR, notes VARCHAR)")
    c.execute("CREATE TABLE author (author_id VARCHAR, outlet_id VARCHAR, canonical_name VARCHAR, "
              "first_seen_at TIMESTAMP, last_seen_at TIMESTAMP)")
    c.execute("CREATE TABLE article (article_id VARCHAR, outlet_id VARCHAR, url VARCHAR, title VARCHAR, "
              "published_at TIMESTAMP, category VARCHAR, language VARCHAR, word_count INTEGER, "
              "word_count_source VARCHAR, metric_completeness VARCHAR, source_type VARCHAR, "
              "extraction_method VARCHAR, extraction_confidence DOUBLE, first_seen_at TIMESTAMP, "
              "last_seen_at TIMESTAMP)")
    c.execute("CREATE TABLE article_author (article_id VARCHAR, author_id VARCHAR, author_order INTEGER)")
    c.execute("INSERT INTO outlet VALUES ('cnn','CNN','cnn.com','feed','u',NULL),"
              "('fox','FOX News','foxnews.com','feed','u',NULL)")

    def ins(aid, outlet, wc, pub_sql, cat="politics"):
        c.execute(
            "INSERT INTO article (article_id, outlet_id, url, title, published_at, category, "
            "language, word_count, first_seen_at, last_seen_at) VALUES "
            f"('{aid}','{outlet}','u/{aid}','title {aid}',{pub_sql},'{cat}','en',{wc},"
            f"{pub_sql},{pub_sql})"
        )

    # recent (always within 90 days of "today")
    ins("a1", "cnn", 100, "CAST(current_date - INTERVAL 2 DAY AS TIMESTAMP)")
    ins("a2", "cnn", 200, "CAST(current_date - INTERVAL 1 DAY AS TIMESTAMP)")
    ins("a3", "fox", 150, "CAST(current_date - INTERVAL 2 DAY AS TIMESTAMP)")
    # old, in the final week of Sept 2025 (outside 90 days)
    ins("a4", "cnn", 400, "CAST('2025-09-25' AS TIMESTAMP)")
    return c


@pytest.fixture
def conn():
    return make_db()


def test_build_sql_outlet_comparison():
    q = MetricQuery(metrics=["articles", "avg_words"], dimension="outlet",
                    outlets=["cnn", "fox"], days=90)
    sql, params = build_sql(q)
    assert "FROM article a" in sql
    assert "GROUP BY a.outlet_id" in sql
    assert "a.outlet_id IN (?, ?)" in sql
    assert "INTERVAL '1 DAY'" in sql
    assert params == ["cnn", "fox", 90]
    # parameterized, no string interpolation of filters
    assert "'cnn'" not in sql and "'fox'" not in sql


def test_build_sql_date_range_and_author_join():
    q = MetricQuery(metrics=["avg_words"], dimension="author",
                    author="vine", start="2025-09-24", end="2025-09-30")
    sql, params = build_sql(q)
    assert "JOIN article_author" in sql
    assert "au.canonical_name ILIKE ?" in sql
    assert params == ["%vine%", "2025-09-24", "2025-09-30"]


def test_validation_rejects_unknown_metric_and_outlet():
    with pytest.raises(QueryError):
        MetricQuery(metrics=["hacks"]).validate()
    with pytest.raises(QueryError):
        MetricQuery(outlets=["not-an-outlet"]).validate(valid_outlets={"cnn", "fox"})


def test_example_compare_cnn_fox(conn):
    def stub(prompt: str) -> str:
        return json.dumps({"metrics": ["articles", "avg_words"], "dimension": "outlet",
                           "outlets": ["cnn", "fox"], "days": 90})
    text = answer("Compare the volume and average length of articles between CNN and "
                  "FOX News over the past 90 days.", conn, stub, {"cnn", "fox"}, set())
    # cnn recent: 2 articles (100,200) avg 150 ; fox: 1 article (150) avg 150
    assert "cnn" in text and "fox" in text
    assert "2 articles" in text and "1 articles" in text
    assert "150.0" in text


def test_example_cnn_final_week_september(conn):
    def stub(prompt: str) -> str:
        return json.dumps({"metrics": ["articles", "avg_words"], "dimension": None,
                           "outlets": ["cnn"], "start": "2025-09-24", "end": "2025-09-30"})
    text = answer("Show me the volume and average length of articles published by CNN "
                  "during the final week of September 2025.", conn, stub, {"cnn", "fox"}, set())
    assert "1 articles" in text and "400.0" in text


def test_no_results_message(conn):
    q = MetricQuery(metrics=["articles"], dimension=None, outlets=["cnn"],
                    start="1999-01-01", end="1999-01-02")
    rows = run_query(conn, q)
    assert chat.format_answer(q, rows).startswith("No matching articles")


def test_rules_fallback_parser():
    q = chat.parse_question_rules("compare article volume for cnn vs fox over the last 30 days",
                                  {"cnn", "fox"}, set())
    assert q.dimension == "outlet"
    assert set(q.outlets) == {"cnn", "fox"}
    assert q.days == 30


def test_rejects_individual_article_superlative():
    with pytest.raises(QueryError):
        chat.parse_question_rules("which article is the longest", {"cnn"}, set())
    with pytest.raises(QueryError):
        chat.parse_question_rules("which outlet has the 3rd largest article by word count",
                                  {"cnn", "fox"}, set())


def test_llm_failure_falls_back_to_rules(conn):
    def bad_llm(prompt: str) -> str:
        raise RuntimeError("llm down")

    text = answer("compare article volume for cnn vs fox over the last 30 days",
                  conn, bad_llm, {"cnn", "fox"}, set())
    assert "cnn" in text and "fox" in text


def test_prompt_has_no_stray_format_braces():
    from datetime import date

    from newsstats.chat import _PROMPT
    # a literal brace in the template would make .format() raise
    _PROMPT.format(outlets="cnn,fox", categories="politics",
                   today=date.today().isoformat(), question="test")
