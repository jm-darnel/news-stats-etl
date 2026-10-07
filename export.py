"""Export marts to static JSON. Usage: python export.py [--out dashboard]"""

from __future__ import annotations

import argparse

from newsstats import export, load


def main() -> None:
    ap = argparse.ArgumentParser(description="Export marts to dashboard JSON")
    ap.add_argument("--db", default=None, help="DuckDB path or MotherDuck md: URL")
    ap.add_argument("--out", default="dashboard", help="output directory")
    args = ap.parse_args()
    conn = load.connect(args.db)
    summary = export.export_dashboard(conn, args.out)
    print(f"exported -> {args.out}/data  ({summary})")


if __name__ == "__main__":
    main()
