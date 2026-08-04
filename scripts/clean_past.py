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

# FIX 4: tombstoned rows (absent_since set) that have been dead for longer
# than this many days are hard-deleted so dead rows don't accumulate forever.
TOMBSTONE_MAX_AGE_DAYS = 30


def clean_tombstones(max_age_days: int = TOMBSTONE_MAX_AGE_DAYS) -> int:
    """Purge tombstoned events whose absent_since is older than max_age_days.

    A row that has been gone (absent_since set) for longer than the threshold
    is considered permanently dead and is removed outright. Newer tombstones
    are kept so a reappearing event can still be resurrected. Honours
    CHAMONIX_DB via storage's get_storage(). Returns count purged.
    """
    from scripts.storage import get_storage
    s = get_storage()
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    with s.conn:
        cur = s.conn.execute(
            "DELETE FROM events WHERE absent_since IS NOT NULL AND absent_since < ?",
            (cutoff,),
        )
    return cur.rowcount


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


def clean_review_queue(max_age_days: int = 21) -> int:
    """Auto-age-out 'open' review items whose event date has passed AND that
    have been sitting unreviewed for > max_age_days. Prevents the review queue
    from growing unbounded with stale below-threshold events (T-fix H2).
    Returns count purged.
    """
    from scripts.storage import get_storage
    s = get_storage()
    from datetime import datetime, timedelta, timezone
    today = date.today().isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    with s.conn:
        rows = s.conn.execute(
            "SELECT id, event_snapshot, created_at FROM review_items WHERE status='open'"
        ).fetchall()
        purge_ids = []
        for r in rows:
            snap = {}
            try:
                import json
                snap = json.loads(r["event_snapshot"]) if r["event_snapshot"] else {}
            except Exception:
                snap = {}
            event_date = snap.get("start_date") or snap.get("startDate") or ""
            created = r["created_at"] or ""
            # purge only if the event date is in the past AND item is old enough
            if event_date and event_date[:10] < today and created and created < cutoff:
                purge_ids.append(r["id"])
        if purge_ids:
            placeholders = ",".join("?" * len(purge_ids))
            s.conn.execute(
                f"DELETE FROM review_items WHERE id IN ({placeholders})",
                purge_ids,
            )
    return len(purge_ids)


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

    # SQLite mode (default): purge events + cinema_events + stale review items
    events_removed = clean_sqlite("events")
    cinema_removed = clean_sqlite("cinema_events")
    review_removed = clean_review_queue(max_age_days=21)
    # FIX 4: purge tombstoned rows whose absent_since is older than the
    # threshold (so dead rows don't accumulate forever).
    tombstone_removed = clean_tombstones()

    if (events_removed or cinema_removed or review_removed or tombstone_removed):
        print(f"Purged {events_removed} past events, {cinema_removed} past cinema events, "
              f"{review_removed} stale review items, {tombstone_removed} old tombstones")
    else:
        print("No past events to remove")
    return 0


if __name__ == "__main__":
    sys.exit(main())