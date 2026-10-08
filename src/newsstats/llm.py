"""Thin OpenRouter-compatible chat-completions client used to parse questions.

Dependency-light (urllib only) so the Vercel serverless function needs no
extra packages beyond duckdb. The API key and model come from the environment.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_MODEL = "z-ai/glm-4.5-air"


def chat(prompt: str, retries: int = 5) -> str:
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("NEWSSTATS_LLM_KEY")
    if not key:
        raise RuntimeError("no LLM API key configured (OPENROUTER_API_KEY)")
    model = os.environ.get("NEWSSTATS_LLM_MODEL", DEFAULT_MODEL)
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{base}/chat/completions",
                data=json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                }).encode(),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            last_exc = e
            time.sleep(2 ** attempt)  # exponential backoff on rate limit / 5xx
        except Exception as e:  # noqa: BLE001
            last_exc = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"LLM call failed after {retries} attempts: {last_exc}") from last_exc
