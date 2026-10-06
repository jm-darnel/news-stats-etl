"""Load and validate sources.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from newsstats.models import SourceConfig

_REQUIRED = ("outlet_id", "name", "domain", "discovery", "feed_url")
_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "sources.yaml"


class SourceConfigError(ValueError):
    pass


def load_sources(path: str | Path = _DEFAULT_PATH) -> list[SourceConfig]:
    data = yaml.safe_load(Path(path).read_text())
    outlets = (data or {}).get("outlets", [])
    if not outlets:
        raise SourceConfigError(f"no outlets in {path}")
    configs: list[SourceConfig] = []
    for i, raw in enumerate(outlets):
        missing = [k for k in _REQUIRED if k not in raw]
        if missing:
            raise SourceConfigError(f"outlet #{i} missing keys: {missing}")
        if raw["discovery"] not in ("rss", "sitemap"):
            raise SourceConfigError(f"outlet {raw['outlet_id']}: bad discovery {raw['discovery']}")
        configs.append(
            SourceConfig(
                outlet_id=raw["outlet_id"],
                name=raw["name"],
                domain=raw["domain"],
                discovery=raw["discovery"],
                feed_url=raw["feed_url"],
                notes=raw.get("notes", ""),
                category_map=raw.get("category_map", {}) or {},
            )
        )
    return configs


def get_source(outlet_id: str, path: str | Path = _DEFAULT_PATH) -> SourceConfig:
    for cfg in load_sources(path):
        if cfg.outlet_id == outlet_id:
            return cfg
    raise SourceConfigError(f"unknown outlet_id: {outlet_id}")
