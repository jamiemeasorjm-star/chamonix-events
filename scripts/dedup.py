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

import html
import re
import unicodedata
from typing import Any


def normalize_title(title: str) -> str:
    """Plan §4.4: NFKD + strip combining marks + drop punctuation/whitespace.

    Cross-source (CROSS_SOURCE_DEDUP_SPEC): HTML entities are decoded first so
    that e.g. unidivers "d&rsquo;orgue" and chamonix_fr "d'orgue" compare equal.
    """
    if not title:
        return ""
    t = title.strip().lower()
    t = html.unescape(t)  # &rsquo; -> ', &amp; -> &, etc.
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


# Rough source trust for merging (CROSS_SOURCE_DEDUP_SPEC): official sources
# (chamonix_fr/com/net) are high; the aggregator (unidivers) is medium. We
# prefer official when confidence + completeness tie.
SOURCE_TRUST = {
    "curated": 2,
    "manual_submission": 2,
    "unidivers": 0,
}


def _source_trust(event: dict[str, Any]) -> int:
    return SOURCE_TRUST.get(event.get("source_id") or "", 1)


def best_of(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the best event from a group of same-(title,date) candidates.

    Order of preference:
      1. Highest confidence
      2. Most fields filled
      3. Higher source trust (official > aggregator)
      4. Lowest source_id alphabetically (deterministic)
    """
    if len(group) == 1:
        return group[0]
    return sorted(
        group,
        key=lambda e: (
            -(e.get("confidence") or 0.0),       # higher confidence first
            -field_completeness(e),              # more fields first
            -_source_trust(e),                   # official over aggregator
            e.get("source_id") or "",            # deterministic tie-break
        ),
    )[0]


# --- Second-stage fuzzy matching (CROSS_SOURCE_DEDUP_SPEC) ------------------
# Unidivers appends "<VENUE> <LOCALITY>" to the event title. After the exact
# normalize_title match (stage 1) we take every event that did NOT collide
# exactly and, within the same start_date, compare their event-name with this
# venue/locality suffix stripped using token-set similarity + prefix matching.

# Multi-token locality phrases (longest/precise first) found as a trailing
# suffix of a normalized title. They are stripped to reveal the underlying
# event name (e.g. "Soirée Indienne Temple Protestant Chamonix-Mont-Blanc" ->
# "Soirée Indienne Temple Protestant").
_LOCALITY_PHRASES: list[tuple[str, ...]] = [
    ("chamonix-mont-blanc",),
    ("haute-savoie",),
    ("chamonix",),
    ("mont-blanc",),
    ("les", "houches"),
    ("les-houches",),
    ("haute", "savoie"),
    ("servoz",),
    ("vallorcine",),
    ("argentiere",),
]

SIM_THRESHOLD = 0.6


def _strip_locality(tokens: list[str]) -> list[str]:
    """Remove trailing locality tokens from a tokenized event title."""
    tokens = list(tokens)
    changed = True
    while changed:
        changed = False
        for phrase in _LOCALITY_PHRASES:
            if len(tokens) >= len(phrase) and tokens[-len(phrase):] == list(phrase):
                del tokens[-len(phrase):]
                changed = True
                break
    return tokens


def _fuzzy_event_name(event: dict[str, Any]) -> list[str]:
    """Tokenized event-name of a title, trailing locality stripped."""
    return _strip_locality(normalize_title(event.get("title", "")).split())


def _tokens_similarity(a: list[str], b: list[str]) -> float:
    """Similarity of two tokenized event-names.

    Returns 1.0 when one is a strict prefix of the other (the case Unidivers
    triggers by appending a venue) or when they share all tokens; otherwise the
    token-set intersection-over-union (Jaccard).
    """
    if not a or not b:
        return 0.0
    # One title is a prefix of the other (after locality stripping) => same
    # underlying event with a venue suffix appended. Require >= 2 tokens so we
    # don't over-merge short generic prefixes.
    if len(a) >= 2 and len(b) >= 2 and len(a) != len(b):
        if b[:len(a)] == a or a[:len(b)] == b:
            return 1.0
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def _fuzzy_cluster(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge events that share a start_date and similar event-name.

    Uses union-find over pairwise similarity so transitivity is handled
    consistently (A~B and B~C collapses all three even if A~C is weak).
    """
    n = len(group)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    names = [_fuzzy_event_name(ev) for ev in group]
    for i in range(n):
        for j in range(i + 1, n):
            if _tokens_similarity(names[i], names[j]) >= SIM_THRESHOLD:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)
    return [best_of([group[i] for i in idxs]) for idxs in clusters.values()]


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cross-source dedup. Returns one event per (normalized_title, start_date).

    Stage 1: exact bucket by (normalize_title, start_date) — unchanged behavior.
    Stage 2: within each start_date, fuzzy-merge events whose event-name
    (locality suffix stripped) is prefix- or token-similar, collapsing the
    Unidivers "<VENUE> <LOCALITY>" duplicates that exact matching misses.
    """
    if not events:
        return []
    # Stage 1: exact buckets (preserve behaviour: skip empty key rows).
    buckets: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        key = dedup_key(ev)
        if not key or key == "|":  # skip rows with no usable key
            continue
        buckets.setdefault(key, []).append(ev)
    reps = [best_of(g) for g in buckets.values()]

    # Stage 2: fuzzy merge on the same start_date.
    by_date: dict[str, list[dict[str, Any]]] = {}
    for rep in reps:
        date = (rep.get("start_date") or "")[:10]
        by_date.setdefault(date, []).append(rep)

    out: list[dict[str, Any]] = []
    for group in by_date.values():
        if len(group) == 1:
            out.append(group[0])
        else:
            out.extend(_fuzzy_cluster(group))

    out.sort(key=lambda e: ((e.get("start_date") or "")[:10], e.get("title") or ""))
    return out


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
