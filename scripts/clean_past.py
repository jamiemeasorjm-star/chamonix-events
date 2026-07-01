#!/usr/bin/env python3
"""Remove events whose end_date (or start_date) is before today.

Phase 2 / T10 follow-on: operates on SQLite (canonical) when --json
is NOT passed. Falls back to legacy JSON-file mode for compatibility
with the old refresh script's cinema-events path.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def clean_sqlite(table: str) -> int:
    """Remove rows whose end_date (or start_date) is before today. Returns count purged."""
    from scripts.storage import get_storage
    s = get_storage()
    today = date.today().isoformat()
    with s.conn:
        # SELECT first so we can report the count
        rows = s.conn.execute(
            f"SELECT id, end_date, start_date FROM {table}"
        ).fetchall()
        purge_ids = [
            r["id"] for r in rows
            if (r["end_date"] or r["start_date"] or "")[:10] < today
        ]
        if purge_ids:
            placeholders = ",".join("?" * len(purge_ids))
            s.conn.execute(
                f"DELETE FROM {table} WHERE id IN ({placeholders})",
                purge_ids,
            )
    return len(purge_ids)


def clean_json(path: str) -> int:
    today = date.today().isoformat()
    with open(path) as f:
        events = json.load(f)
    before = len(events)
    events = [e for e in events if (e.get('end_date') or e.get('start_date') or '')[:10] >= today]
    # Atomic write — same crash-safety as T03
    from scripts.models import write_atomic_json
    write_atomic_json(path, events)
    return before - len(events)


def main() -> int:
    args = sys.argv[1:]

    # Legacy mode: a path argument means operate on the JSON file directly
    # (used for cinema_events.json until T10 also moves it).
    if args and not args[0].startswith("--"):
        path = args[0]
        removed = clean_json(path)
        remaining = (lambda d: len(d))(json.load(open(path)))
        if removed:
            print(f'Purged {removed} past events, {remaining} remaining')
        else:
            print(f'No past events to remove ({remaining} events)')
        return 0

    # SQLite mode (default): purge events + cinema_events
    events_removed = clean_sqlite("events")
    cinema_removed = clean_sqlite("cinema_events")

    if events_removed or cinema_removed:
        print(f"Purged {events_removed} past events, {cinema_removed} past cinema events")
    else:
        print("No past events to remove")
    return 0


if __name__ == "__main__":
    sys.exit(main())