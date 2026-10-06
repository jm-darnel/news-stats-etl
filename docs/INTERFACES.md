# Frozen Interfaces (M0)

This file is the contract every worker builds against. Do not change the shapes
below without updating this file first and re-freezing. If a worker needs a new
field or a signature change, it stops and raises it, it does not invent one.

The rule that makes the design work: **per-outlet quirks live only in
`sources.yaml`.** Every module below is outlet-agnostic.

---

## 1. Canonical schema

Authoritative DDL in `migrations/0001_initial.sql`. Tables: `outlet`, `article`,
`author`, `article_author`, `ingest_run`, `dq_result`. Ids are content hashes
(`md5(url)` for articles, `md5(outlet_id + '|' + normalized_name)` for authors)
so re-runs are idempotent.

Key enums:

- `word_count_source`: `native` | `derived`
- `metric_completeness`: `full` | `volume_only`
- `source_type`: `rss` | `sitemap` | `gdelt` | `ccnews`
- `extraction_method`: e.g. `trafilatura`, `json-ld`, `meta`

## 2. Canonical record (the shape everything emits)

`src/newsstats/models.py`:

```python
@dataclass(frozen=True)
class DiscoveredArticle:
    outlet_id: str
    url: str
    title: str | None
    published_at: str | None     # ISO 8601 from the feed, else None
    category: str | None         # from the feed, else None
    discovered_at: str           # ISO 8601, set by us

@dataclass(frozen=True)
class ExtractedArticle:
    url: str
    title: str | None
    authors: list[str]           # parsed bylines, [] if none
    published_at: str | None     # ISO 8601
    category: str | None
    language: str | None
    text: str                    # body, transient, never persisted
    word_count: int
    word_count_source: str       # native | derived
    extraction_method: str
    extraction_confidence: float # 0.0..1.0

@dataclass(frozen=True)
class CanonicalArticle:
    article_id: str
    outlet_id: str
    url: str
    title: str | None
    authors: list[str]
    published_at: str | None
    category: str | None
    language: str | None
    word_count: int | None
    word_count_source: str
    metric_completeness: str
    source_type: str
    extraction_method: str
    extraction_confidence: float
    first_seen_at: str
    last_seen_at: str
```

## 3. Module contracts and file ownership

One worker owns one module. No two workers touch the same file.

| Worker | File(s) | Contract |
|---|---|---|
| config | `src/newsstats/config.py` | `load_sources(path) -> list[SourceConfig]`; validates required keys |
| discover | `src/newsstats/discover.py` | `discover(source) -> list[DiscoveredArticle]`; handles `rss` and `sitemap` discovery; trims feed-link whitespace; does not fetch article bodies |
| fetch | `src/newsstats/fetch.py` | `fetch_html(url) -> str`; browser-like UA, per-domain polite delay, retry with backoff |
| extract | `src/newsstats/extract.py` | `extract_article(html, url) -> ExtractedArticle`; trafilatura primary, JSON-LD/meta fallbacks for author + category; computes `word_count`; measures the body, never trusts a paywall flag |
| normalize | `src/newsstats/normalize.py` | `to_canonical(discovered, extracted, source) -> CanonicalArticle`; parses bylines into `authors`; assigns hashes and enums |
| load | `src/newsstats/load.py` | `connect(url)`, `init_schema(conn)`, `upsert(conn, rows)`; idempotent upsert |
| orchestrate | `etl.py` | CLI: `--source`, `--limit`, `--dry-run`; wires the modules; writes `ingest_run` |
| models (shared) | `src/newsstats/models.py` | dataclasses + hash/id helpers. Shared, owned by the interface freeze, not a worker |

## 4. sources.yaml schema

See the file header comment. Required keys per outlet: `outlet_id`, `name`,
`domain`, `discovery`, `feed_url`. Optional: `notes`, `category_map`.
Adding or removing a source is a config edit, never a code edit.

## 5. Acceptance tests (what done means per module)

- config: `load_sources` returns all 22 outlets, each with the required keys.
- discover: for a saved fixture feed, returns articles whose URLs parse and look like articles.
- extract: for each fixture HTML, `word_count > 0`; author and category match the probe expectation for that outlet where one exists.
- normalize: byline "By Jane Doe and John Smith" -> `["Jane Doe", "John Smith"]`; "Staff" / "CNN Wire" -> `[]` plus unattributed handling; ids are stable hashes.
- load: upserting the same rows twice leaves the row count unchanged.
- integration: `python etl.py --source slate --limit 1` produces one row with `word_count > 0` and a category; `--source fox --limit 1` proves the `dc.creator` author path.

## 6. Hard rules for workers

- Persist metadata + derived metrics only. Never persist the body text or HTML.
- Mark paywalled/blocked sources by `extraction_confidence`, not by dropping data.
- `word_count` is whitespace tokens of the extracted body. Document any deviation.
- No new external API calls, dependencies, or files outside your assigned module without raising it first.
- Every module ships with its acceptance test passing.
