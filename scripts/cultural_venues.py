#!/usr/bin/env python3
"""Ingest cultural venue events from CSV (T35).

Reads data/cultural_venues.csv and upserts events into the storage layer
with source_id='cultural_venues' and confidence=0.61 (just above the 0.6
auto-publish threshold so they appear on the site without review).

CSV format: title,start_date,end_date,time,category,venue_name,commune,description,source_url

Usage:
    python3 -m scripts.cultural_venues           # insert/update
    python3 -m scripts.cultural_venues --dry-run  # preview without writing
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.storage import get_storage  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
CSV_PATH = HERE / "data" / "cultural_venues.csv"
SOURCE_ID = "cultural_venues"
CONFIDENCE = 0.61  # above 0.6 threshold → auto-publish
NOW = datetime.now(timezone.utc).isoformat()


def parse_csv(path: Path) -> list[dict]:
    """Read the CSV and return event dicts."""
    events = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            # Skip comments and empty lines
            if not row or row[0].startswith("#"):
                continue
            if len(row) < 9:
                continue

            title, start_date, end_date, time_val, category, venue_name, commune, desc, source_url = row[:9]
            title = title.strip()
            start_date = start_date.strip()
            if not title or not start_date:
                continue

            event = {
                "title": title,
                "start_date": start_date,
                "end_date": end_date.strip() or None,
                "time": time_val.strip() or None,
                "category": category.strip(),
                "venue_name": venue_name.strip(),
                "commune": commune.strip(),
                "description": desc.strip(),
                "source_url": source_url.strip() or "",
                "source_id": SOURCE_ID,
                "image_url": "",
                "confidence": CONFIDENCE,
                "created_at": NOW,
                "updated_at": NOW,
                "status": "published",
            }
            events.append(event)
    return events


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    if not CSV_PATH.exists():
        print(f"[cultural_venues] CSV not found: {CSV_PATH}", file=sys.stderr)
        return 1

    events = parse_csv(CSV_PATH)
    if not events:
        print("[cultural_venues] No events found in CSV")
        return 0

    print(f"[cultural_venues] Loaded {len(events)} events from {CSV_PATH.name}")

    if dry_run:
        print(f"[cultural_venues] DRY RUN — would insert {len(events)} events:")
        for e in events:
            print(f"  {e['start_date']}  {e['title'][:50]:50s}  {e['venue_name']}")
        return 0

    # Upsert via storage
    s = get_storage()
    s.upsert_events_ungated(SOURCE_ID, events)

    print(f"[cultural_venues] Inserted/updated {len(events)} events (confidence={CONFIDENCE})")
    return 0


if __name__ == "__main__":
    sys.exit(main())