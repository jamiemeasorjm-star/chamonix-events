"""Source registry loader for Chamonix Events.

Phase 2 / T13. Reads sources.yaml and provides a list of Source dataclasses.
Caches the result in memory after first load (sources.yaml is static — restart
to pick up changes).

Usage:
    from scripts.sources import load_sources, get_source

    sources = load_sources()
    for s in sources:
        if s.active:
            print(s.id, s.trust_level, s.confidence_baseline())

    chamonix = get_source("chamonix_net")
    print(chamonix.confidence_baseline())  # 1.0
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.models import Source, TRUST_BASELINE


def _find_sources_yaml() -> Path:
    """Locate sources.yaml — project root first, then current working dir."""
    candidates = [
        Path(__file__).resolve().parent.parent / "sources.yaml",
        Path.cwd() / "sources.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "sources.yaml not found. Looked in: " + ", ".join(str(c) for c in candidates)
    )


_cache: Optional[list[Source]] = None
_by_id: dict[str, Source] = {}
_global_threshold: float = 0.4  # default if sources.yaml has no key


def load_sources(force_reload: bool = False) -> list[Source]:
    """Return the list of Source objects from sources.yaml. Cached after first call."""
    global _cache, _by_id, _global_threshold
    if _cache is not None and not force_reload:
        return _cache

    path = _find_sources_yaml()
    with open(path) as f:
        data = yaml.safe_load(f)

    # T26: global publish threshold (optional; falls back to module default).
    if isinstance(data, dict):
        raw_t = data.get("min_publish_confidence")
        if raw_t is not None:
            try:
                _global_threshold = float(raw_t)
            except (TypeError, ValueError):
                pass  # keep previous value on bad config

    raw_sources = data.get("sources", []) if isinstance(data, dict) else []
    sources: list[Source] = []
    for r in raw_sources:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        s = Source(
            id=str(r["id"]),
            name=str(r.get("name", r["id"])),
            type=str(r.get("type", "scraper")),
            base_url=r.get("base_url"),
            trust_level=str(r.get("trust_level", "medium")),
            ingestion_cadence_hours=r.get("ingestion_cadence_hours"),
            active=bool(r.get("active", True)),
            notes=str(r.get("notes", "")),
        )
        # T26: per-source override of the global publish threshold.
        raw_pt = r.get("min_publish_confidence")
        if raw_pt is not None:
            try:
                s.min_publish_confidence = float(raw_pt)
            except (TypeError, ValueError):
                pass
        sources.append(s)

    _cache = sources
    _by_id = {s.id: s for s in sources}
    return sources


def get_source(source_id: str) -> Optional[Source]:
    """Lookup a Source by id; loads sources.yaml on first call."""
    if not _by_id:
        load_sources()
    return _by_id.get(source_id)


def get_min_confidence(source_id: str) -> float:
    """T26: per-source publish threshold.

    Returns the source's `min_publish_confidence` if set, else the global
    default. Always loads sources.yaml first.
    """
    s = get_source(source_id)
    if s is not None and s.min_publish_confidence is not None:
        return s.min_publish_confidence
    if not _by_id:
        load_sources()
    return _global_threshold


def get_default_min_confidence() -> float:
    """T26: the global default threshold (no per-source lookup)."""
    if not _by_id:
        load_sources()
    return _global_threshold


def active_sources() -> list[Source]:
    """Return only sources where active=true."""
    return [s for s in load_sources() if s.active]


def trust_summary() -> dict[str, int]:
    """Return {trust_level: count} for active sources. Useful for logs."""
    summary = {"high": 0, "medium": 0, "low": 0}
    for s in active_sources():
        summary[s.trust_level] = summary.get(s.trust_level, 0) + 1
    return summary


if __name__ == "__main__":
    # CLI for verification
    for s in load_sources(force_reload=True):
        flag = "ACTIVE" if s.active else "disabled"
        baseline = s.confidence_baseline()
        print(f"  {s.id:20s}  trust={s.trust_level:6s}  baseline={baseline}  [{flag}]  {s.name}")
    print()
    print("Trust summary:", trust_summary())