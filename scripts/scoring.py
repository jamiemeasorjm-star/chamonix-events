"""Confidence scoring for Chamonix Events.

Phase 2 / T14. Implements the formula from plan §8.2:

    confidence = source_trust × parse_quality × completeness

- source_trust: from sources.yaml (high=1.0, medium=0.8, low=0.55)
- parse_quality: fraction of EXPECTED fields successfully extracted for
  this source (e.g., chamonix_net is expected to deliver title + date +
  description + venue; chamonix_com listing-only is expected to deliver
  title + URL only; vox_pdf is expected to deliver title + duration +
  showtimes)
- completeness: fraction of non-empty fields among the canonical 7
  display fields (title, start_date, end_date, time, venue_name,
  description, address)

The result is rounded to 3 decimal places. Events with confidence < 0.6
will be routed to the review queue by T26 (Phase 3) — that gate is NOT
applied here; T14 just computes the score.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.models import Source
from scripts.sources import get_source


# Fields we expect each source to extract at scrape time. The denominator
# for parse_quality is len(this list). If a field is missing from the
# source's typical page structure, parse_quality drops.
EXPECTED_FIELDS: dict[str, list[str]] = {
    "chamonix_net": ["title", "start_date", "description", "image_url"],
    "chamonix_com": ["title", "start_date"],  # listing-only today; detail scraper pending
    "vox_pdf": ["title", "duration", "showtimes"],
    "allocine_vox": ["title", "start_date"],
    "chamonix_nightlife": ["title", "start_date", "image_url"],
    "cultural_venues": ["title", "start_date", "image_url"],
    "manual_submission": ["title", "start_date", "venue_name"],
}


# Canonical display fields used for completeness. Same set as plan §8.2.
COMPLETENESS_FIELDS = (
    "title", "start_date", "end_date", "time",
    "venue_name", "description", "address",
)


def parse_quality(source_id: str, event: dict[str, Any]) -> float:
    """Fraction of expected fields present in this event."""
    expected = EXPECTED_FIELDS.get(source_id, ["title", "start_date"])
    if not expected:
        return 1.0
    present = sum(1 for f in expected if _has_value(event.get(f)))
    return present / len(expected)


def completeness(event: dict[str, Any]) -> float:
    """Fraction of canonical display fields that are non-empty."""
    if not COMPLETENESS_FIELDS:
        return 1.0
    present = sum(1 for f in COMPLETENESS_FIELDS if _has_value(event.get(f)))
    return present / len(COMPLETENESS_FIELDS)


def compute_confidence(source_id: str, event: dict[str, Any]) -> float:
    """Plan §8.2: trust × parse_quality × completeness, rounded to 3 dp."""
    source = get_source(source_id)
    trust = source.confidence_baseline() if source else 0.5
    pq = parse_quality(source_id, event)
    c = completeness(event)
    return round(trust * pq * c, 3)


def explain(source_id: str, event: dict[str, Any]) -> dict[str, float]:
    """Diagnostic: return the components separately for logging."""
    source = get_source(source_id)
    trust = source.confidence_baseline() if source else 0.5
    pq = parse_quality(source_id, event)
    c = completeness(event)
    return {
        "trust": trust,
        "parse_quality": round(pq, 3),
        "completeness": round(c, 3),
        "confidence": round(trust * pq * c, 3),
    }


def _has_value(v: Any) -> bool:
    """A field counts as 'present' if it's not None, '', [], or {}."""
    if v is None:
        return False
    if isinstance(v, str) and v.strip() == "":
        return False
    if isinstance(v, (list, dict)) and len(v) == 0:
        return False
    return True


def distribution_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Bucket confidences for a log-friendly summary."""
    buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    for r in rows:
        c = r.get("confidence", 0.0)
        if c < 0.2:
            buckets["0.0-0.2"] += 1
        elif c < 0.4:
            buckets["0.2-0.4"] += 1
        elif c < 0.6:
            buckets["0.4-0.6"] += 1
        elif c < 0.8:
            buckets["0.6-0.8"] += 1
        else:
            buckets["0.8-1.0"] += 1
    return buckets


if __name__ == "__main__":
    # Self-test / demo
    test_events = [
        {"title": "Tournoi de Volley", "start_date": "2026-07-01"},  # bare minimum
        {"title": "Arc'teryx Alpine Academy", "start_date": "2026-07-02",
         "description": "The 14th edition returns to Chamonix...", "venue_name": "Plan Joran",
         "image_url": "https://...", "time": "09:00"},  # rich event
    ]
    print("chamonix_net distribution:")
    for ev in test_events:
        print(f"  {ev['title'][:40]:40s}  {explain('chamonix_net', ev)}")
    print()
    print("chamonix_com distribution:")
    for ev in test_events:
        print(f"  {ev['title'][:40]:40s}  {explain('chamonix_com', ev)}")
    print()
    print("vox_pdf distribution:")
    cinema = {"title": "TOY STORY 5", "duration": "1h42", "showtimes": {"2026-06-30": ["15:00"]}}
    print(f"  {cinema['title']:40s}  {explain('vox_pdf', cinema)}")