"""Vercel serverless function: POST /api/chat  {"question": "..."}  ->  {"answer": "..."}.

Constrained metric-query chatbot. The question is compiled to a whitelisted
MetricQuery (never free SQL), validated, and run against the MotherDuck
warehouse. If an LLM key is configured (OPENROUTER_API_KEY) the question is
parsed by the model; otherwise a deterministic rule parser handles common
phrasings.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import duckdb  # noqa: E402

# Serverless filesystems have no writable HOME; DuckDB (and the MotherDuck
# extension download) needs one. /tmp is the only writable dir on Vercel.
os.environ.setdefault("HOME", "/tmp")

from newsstats import chat as chatmod  # noqa: E402
from newsstats import llm  # noqa: E402

DB_URL = os.environ.get("NEWSSTATS_DB_URL", "md:newsstats")


def _connect():
    return duckdb.connect(DB_URL, config={"home_directory": "/tmp"})


def _has_llm_key() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("NEWSSTATS_LLM_KEY"))


class handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            question = (data.get("question") or "").strip()
            if not question:
                return self._send(400, {"error": "missing 'question'"})
            conn = _connect()
            try:
                outlets, cats = chatmod.load_whitelists(conn)
                llm_fn = llm.chat if _has_llm_key() else None
                text = chatmod.answer(question, conn, llm_fn, outlets, cats)
            finally:
                conn.close()
            self._send(200, {"answer": text})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})
