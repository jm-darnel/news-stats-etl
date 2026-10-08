"""One-off LLM pass for author resolution (fills rule-based gaps).

Finds names sharing a surname but differing in given name/initial ("Joe Biden"
vs "Joseph Biden") that the deterministic pass can't merge, and asks a cheap LLM
to resolve each cluster to a canonical form. Purely additive: reports merges.
"""

import json
import os
import re
from collections import Counter, defaultdict

import duckdb

from newsstats.author_resolution import canonical_key, split_names
from newsstats.llm import chat

_PROMPT = """You resolve whether news bylines refer to the same person.

For each surname group below, decide which names are ALIASES of the same person
(e.g. "Joe Biden" and "Joseph Biden" ARE the same; "Jane Smith" and "John Smith"
are DIFFERENT people, leave them out).

Return ONLY JSON: {"groups": [{"canonical": "Joseph Biden", "aliases": ["Joe Biden"]}]}
Omit surnames where every name is a distinct person. canonical = the fullest/most
formal form. Keep the same casing as given.

Surname groups:
__GROUPS__
"""


def load_key(path="~/.hermes/.env"):
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        return False
    for line in open(p):
        if line.startswith("OPENROUTER_API_KEY="):
            os.environ["OPENROUTER_API_KEY"] = line.split("=", 1)[1].strip()
            return True
    return False


def extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return json.loads(m.group(0)) if m else {}


def main():
    load_key()
    gd = duckdb.connect("data/gdelt_backfill.duckdb", read_only=True)
    raw = [r[0] for r in gd.execute(
        "SELECT DISTINCT author FROM gdelt_article WHERE author IS NOT NULL").fetchall()]

    display: dict[str, str] = {}
    counts: Counter = Counter()
    for r in raw:
        for n in split_names(r):
            k = canonical_key(n)
            counts[k] += 1
            display.setdefault(k, n)

    by_last: dict[str, set[str]] = defaultdict(set)
    for k in counts:
        toks = k.split()
        if len(toks) >= 2:
            by_last[toks[-1]].add(k)

    # meaningful surname blocks: >=2 variants and at least one with >=2 articles
    blocks = {
        s: sorted(names, key=lambda n: -counts[n])[:8]
        for s, names in by_last.items()
        if len(names) >= 2 and any(counts[n] >= 2 for n in names)
    }
    ordered = sorted(blocks.items(), key=lambda kv: -sum(counts[n] for n in kv[1]))

    # batch ~40 surnames per LLM call
    merges = 0
    for i in range(0, len(ordered), 40):
        chunk = ordered[i:i + 40]
        group_lines = "\n".join(f"{s}: {[display[n] for n in names]}" for s, names in chunk)
        resp = chat(_PROMPT.replace("__GROUPS__", group_lines))
        data = extract_json(resp)
        for g in data.get("groups", []):
            if g.get("aliases"):
                merges += len(g["aliases"])

    print(f"canonical names: {len(counts)}")
    print(f"surname blocks scanned: {len(blocks)}")
    print(f"LLM-resolved alias merges: {merges}")
    gd.close()


if __name__ == "__main__":
    main()
