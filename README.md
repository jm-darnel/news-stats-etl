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

## MotherDuck (hosted DuckDB)

The public dashboard/chatbot read from MotherDuck, not the local file (Vercel and
GitHub Actions cannot reach a local file). Same DuckDB engine, one account.

- Token lives in `.env` (gitignored) as `motherduck_token=...`; `NEWSSTATS_DB_URL=md:newsstats`.
- The `motherduck` extension auto-installs on first `md:` connection (duckdb 1.4.1-1.5.6 supported).
- Free Lite tier: 10 GB storage + 10 compute-hours/month. Run the heavy backfill on local
  DuckDB and keep MotherDuck as the light serving layer.
- Claim ownership of the account via the `claim_org_url` from signup.

```bash
set -a; . ./.env; set +a
python etl.py --source slate --limit 1   # now writes to md:newsstats
```

## Deploy (Vercel)

Static dashboard (`dashboard/`) + one Python serverless function (`api/chat.py`).

- `vercel.json`: `framework: null` (static, not a Python service) + `outputDirectory: dashboard`.
  Without `framework: null`, Vercel sees `pyproject.toml` and misdetects a Python app
  ("No python entrypoint found").
- Serverless function deps come from `requirements.txt` (`duckdb` only). The function adds
  `src/` to `sys.path` and imports `newsstats.chat`/`newsstats.llm` directly, so the heavy
  ETL deps (trafilatura/feedparser) are not installed in the function.

Required Vercel environment variables (Project Settings -> Environment Variables):

| Name | Required | Purpose |
|---|---|---|
| `motherduck_token` | yes | read the warehouse (`md:newsstats`) |
| `OPENROUTER_API_KEY` | optional | LLM question parsing; without it a deterministic rule parser handles common phrasings |
| `NEWSSTATS_LLM_MODEL` | optional | default `deepseek/deepseek-chat` |

Without `motherduck_token` the chatbot returns an IO/auth error; the static charts keep working
(they read committed JSON in `dashboard/data/`, refreshed by `python export.py`).
