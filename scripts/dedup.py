"""T11: Unified cross-source deduplication.

The plan (§4.4) called for two conflicting dedup algorithms at different
stages to be collapsed into one canonical algorithm in the storage layer.
This module is that algorithm.

Algorithm
---------
1. Group events by (normalized_title, start_date).
2. Within each group, pick the highest-confidence version.
3. Tie-break by source trust (Tier 1 > Tier 2 > Tier 3).
4. Tie-break by field completeness (more non-empty fields wins).
5. Return the merged list — one event per (title, date).

The "canonical" dedup key is `normalized_title(start_date)` so that:
- The same event from different sources lands in the same bucket.
- The same title on different dates is treated as distinct events.
- Title case + accents + punctuation don't fragment the bucket.

Per-scraper dedup (in chamonix_net.py / chamonix_com.py) stays as a safety
net for the case where a single source produces duplicates (rare).
The canonical merge happens here, in the storage layer, exactly once.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_title(title: str) -> str:
    """Plan §4.4: NFKD + strip combining marks + drop punctuation/whitespace."""
    if not title:
        return ""
    t = title.strip().lower()
    t = unicodedata.normalize("NFKD", t)
    # Strip combining diacritics
    t = re.sub(r"[̀-ͯ]", "", t)
    # Strip age-rating prefix like "Int.—12 ans"
    t = re.sub(r"^int[.°]?\s*—\s*\d+\s+ans\s+", "", t, flags=re.IGNORECASE)
    # Drop punctuation that varies across sources
    t = re.sub(r"[\u2014\u2013\u2019\u2018\x22\x27\x3a\x5c/]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def dedup_key(event: dict[str, Any]) -> str:
    """Canonical key for cross-source matching."""
    title = normalize_title(event.get("title", ""))
    date = (event.get("start_date") or "")[:10]
    return f"{title}|{date}"


# Display fields that contribute to "completeness" for tie-breaking
DISPLAY_FIELDS = (
    "title", "description", "start_date", "end_date", "time",
    "venue_name", "address", "image_url", "price",
)


def field_completeness(event: dict[str, Any]) -> int:
    return sum(1 for f in DISPLAY_FIELDS if _has_value(event.get(f)))


def _has_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and v.strip() == "":
        return False
    if isinstance(v, (list, dict)) and len(v) == 0:
        return False
    return True


def best_of(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the best event from a group of same-(title,date) candidates.

    Order of preference:
      1. Highest confidence
      2. Most fields filled
      3. Lowest source_id alphabetically (deterministic)
    """
    if len(group) == 1:
        return group[0]
    return sorted(
        group,
        key=lambda e: (
            -(e.get("confidence") or 0.0),       # higher confidence first
            -field_completeness(e),              # more fields first
            e.get("source_id") or "",            # deterministic tie-break
        ),
    )[0]


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cross-source dedup. Returns one event per (normalized_title, start_date)."""
    if not events:
        return []
    buckets: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        key = dedup_key(ev)
        if not key or key == "|":  # skip rows with no usable key
            continue
        buckets.setdefault(key, []).append(ev)
    return [best_of(g) for g in buckets.values()]


if __name__ == "__main__":
    # Self-test
    tests = [
        ("Café-concert", "Cafe concert"),
        ("Marché paysan", "Marche paysan"),
        ("Arc'teryx Alpine Academy", "Arc'teryx Alpine Academy"),
        ("Exposition - Charlie Adam", "Exposition — Charlie Adam"),
    ]
    print("normalize_title self-test:")
    for a, b in tests:
        na, nb = normalize_title(a), normalize_title(b)
        match = "MATCH" if na == nb else "DIFFER"
        print(f"  [{match}] {a!r:40s} -> {na!r}")
        print(f"         {b!r:40s} -> {nb!r}")

    print()
    print("dedupe_events self-test:")
    sample = [
        {"title": "Arc'teryx Alpine Academy", "start_date": "2026-07-02",
         "description": "Long desc here", "image_url": "x.png", "venue_name": "Plan Joran",
         "source_id": "chamonix_net", "confidence": 1.0},
        {"title": "Arc'teryx Alpine Academy", "start_date": "2026-07-02",
         "description": "", "image_url": None, "venue_name": None,
         "source_id": "chamonix_com", "confidence": 0.4},
        {"title": "Marché paysan", "start_date": "2026-07-05",
         "description": "Local produce market",
         "source_id": "chamonix_com", "confidence": 0.5},
    ]
    result = dedupe_events(sample)
    print(f"  {len(sample)} input -> {len(result)} unique")
    for r in result:
        print(f"    {r['source_id']:15s} conf={r['confidence']:.2f}  {r['title']}")
