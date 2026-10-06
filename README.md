# news-stats-etl

Portfolio ETL: scrape ~22 news outlets, extract article metadata (title, authors,
date, category, word count), load into a DuckDB/MotherDuck warehouse, model it
dbt-style, and serve a static dashboard plus a chatbot.

This is JMD-79 ("ETL -> warehouse -> AI dashboard"). The planning docs live in the
Obsidian vault under `Plans/JMD-79*`.

## Status

M0 skeleton: frozen interfaces + one-outlet end-to-end proof.

## Layout

```
sources.yaml          # frozen source registry (per-outlet config, no per-source code)
docs/INTERFACES.md    # THE FROZEN INTERFACE: schema + module contracts + acceptance tests
migrations/           # canonical schema DDL (DuckDB dialect)
src/newsstats/        # pipeline modules
tests/                # unit tests (fixtures) + integration checks
etl.py                # CLI entrypoint
```

## Quick start

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"   # or: uv pip install -e . && uv pip install pytest ruff
python etl.py --source fox --limit 1
python etl.py --source slate --limit 1
```

Set `NEWSSTATS_DB_URL` to point at MotherDuck (`md:newsstats?motherduck_token=...`)
or a local DuckDB file (default `data/warehouse.duckdb`).
