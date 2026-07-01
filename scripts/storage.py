"""SQLite-backed storage for Chamonix Events.

Phase 2 / T10. Replaces JSON file storage for the canonical event/venue/cinema
data. JSON files remain on disk as build artefacts produced by build.py.

Design notes
------------
- DB path: prefers the bind-mounted host path, falls back to the in-container
  bind mount. Same logic as scripts/chamonix-health-check.py (T08).
- Every write is wrapped in a single transaction. SQLite gives us ACID + WAL,
  so a crash mid-write either commits cleanly or rolls back; the on-disk
  file is never partially written.
- JSON->SQLite migration runs once, idempotently, on first DB open. Existing
  events.json / cinema_events.json / venues.json are read and bulk-inserted,
  then a flag in build_metadata prevents re-running.
- The CRUD methods take/return plain dicts (the same shape that the JSON
  files had). Scrapers don't need to know about SQL.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)
from scripts.dedup import dedupe_events  # T11


# ----- DB path resolution ---------------------------------------------------

def resolve_db_path() -> Path:
    """Return the canonical DB path, honouring the CHAMONIX_DB env var if set."""
    if os.environ.get("CHAMONIX_DB"):
        return Path(os.environ["CHAMONIX_DB"])
    for candidate in (
        "/docker/hermes-agent-2bpx/data/chamonix-events/data/chamonix.db",
        "/opt/data/chamonix-events/data/chamonix.db",
    ):
        if Path(candidate).parent.exists():
            return Path(candidate)
    # Last-resort default (host path)
    return Path("/docker/hermes-agent-2bpx/data/chamonix-events/data/chamonix.db")


def resolve_data_dir() -> Path:
    """Return the project data directory (for migration reads)."""
    for d in (
        "/docker/hermes-agent-2bpx/data/chamonix-events/data",
        "/opt/data/chamonix-events/data",
    ):
        if Path(d).exists():
            return Path(d)
    return Path("/docker/hermes-agent-2bpx/data/chamonix-events/data")


# ----- Schema ---------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT DEFAULT '',
    start_date    TEXT,
    end_date      TEXT,
    time          TEXT,
    venue_id      TEXT,
    category      TEXT NOT NULL DEFAULT 'other',
    commune       TEXT DEFAULT 'Chamonix',
    source_url    TEXT,
    image_url     TEXT,
    price         TEXT,
    venue_name    TEXT,
    address       TEXT,
    contact_phone TEXT,
    website       TEXT,
    status        TEXT DEFAULT 'published',
    confidence    REAL DEFAULT 1.0,
    created_at    TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS cinema_events (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    duration       TEXT,
    language       TEXT,
    start_date     TEXT,
    end_date       TEXT,
    showtimes_json TEXT,
    image_url      TEXT,
    description    TEXT,
    source_url     TEXT,
    status         TEXT DEFAULT 'published',
    confidence     REAL DEFAULT 1.0,
    created_at     TEXT,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS venues (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    commune   TEXT DEFAULT 'Chamonix',
    address   TEXT,
    latitude  REAL,
    longitude REAL,
    url       TEXT,
    phone     TEXT,
    source_id TEXT
);

CREATE TABLE IF NOT EXISTS review_items (
    id           TEXT PRIMARY KEY,
    event_id     TEXT,
    reason       TEXT,
    notes        TEXT,
    reviewed_by  TEXT,
    reviewed_at  TEXT,
    status       TEXT DEFAULT 'open',
    created_at   TEXT
);

CREATE TABLE IF NOT EXISTS build_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_source     ON events(source_id);
CREATE INDEX IF NOT EXISTS idx_events_start_date ON events(start_date);
CREATE INDEX IF NOT EXISTS idx_events_status     ON events(status);
"""


# ----- Storage class --------------------------------------------------------

class Storage:
    """Thin SQLite wrapper. Single connection per process, row_factory=dict."""

    def __init__(self, db_path: str | os.PathLike | None = None):
        self.db_path = Path(db_path) if db_path else resolve_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        # WAL gives us better concurrent-read-while-writing behaviour; matters
        # if two scrapers ever run at once.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._maybe_migrate_from_json()

    # ---- schema + migration ----

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)
        # T15: idempotent column adds for review_items (SQLite has no
        # ADD COLUMN IF NOT EXISTS, so we check pragma_table_info first).
        self._add_column_if_missing("review_items", "source_id", "TEXT")
        self._add_column_if_missing("review_items", "event_snapshot", "TEXT")
        # T26: confidence column for fast threshold-aware queries
        # ("list review items below threshold", "stats by source").
        self._add_column_if_missing("review_items", "confidence", "REAL")
        # T18: curated venue seed — categories and postal codes.
        self._add_column_if_missing("venues", "postal_code", "TEXT")
        # categories stored as JSON-encoded list (e.g., '["bar","live_music"]')
        self._add_column_if_missing("venues", "categories", "TEXT")

    def _add_column_if_missing(self, table: str, column: str, decl: str) -> None:
        """SQLite helper: add a column only if it isn't already there.

        Used by forward-only, idempotent migrations. Safe to call on every
        Storage init; no-op when the column already exists.
        """
        cols = {row["name"] for row in self.conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()}
        if column not in cols:
            with self.conn:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def _maybe_migrate_from_json(self) -> None:
        """One-shot migration: copy JSON -> SQLite on first DB open."""
        cur = self.conn.execute(
            "SELECT value FROM build_metadata WHERE key='migrated_from_json'"
        )
        if cur.fetchone() is not None:
            return  # already migrated

        data_dir = resolve_data_dir()
        migrated_any = False

        events_path = data_dir / "events.json"
        if events_path.exists():
            try:
                rows = json.loads(events_path.read_text(encoding="utf-8"))
                if isinstance(rows, list) and rows:
                    self._bulk_insert_events(rows)
                    print(f"  [migrate] {len(rows)} events from {events_path}", flush=True)
                    migrated_any = True
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [migrate] events.json unreadable: {e}", flush=True)

        cinema_path = data_dir / "cinema_events.json"
        if cinema_path.exists():
            try:
                rows = json.loads(cinema_path.read_text(encoding="utf-8"))
                if isinstance(rows, list) and rows:
                    self._bulk_insert_cinema(rows)
                    print(f"  [migrate] {len(rows)} cinema events from {cinema_path}", flush=True)
                    migrated_any = True
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [migrate] cinema_events.json unreadable: {e}", flush=True)

        venues_path = data_dir / "venues.json"
        if venues_path.exists():
            try:
                rows = json.loads(venues_path.read_text(encoding="utf-8"))
                if isinstance(rows, list) and rows:
                    self._bulk_insert_venues(rows)
                    print(f"  [migrate] {len(rows)} venues from {venues_path}", flush=True)
                    migrated_any = True
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [migrate] venues.json unreadable: {e}", flush=True)

        # Mark migrated regardless — even if all three files were empty,
        # we don't want to retry on every startup.
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO build_metadata (key, value) VALUES (?, ?)",
                ("migrated_from_json", datetime.now(timezone.utc).isoformat()),
            )
            if migrated_any:
                self.conn.execute(
                    "INSERT OR REPLACE INTO build_metadata (key, value) VALUES (?, ?)",
                    ("migration_had_data", "1"),
                )

    # ---- bulk inserts (migration only) ----

    def _bulk_insert_events(self, rows: list[dict]) -> None:
        cols = (
            "id", "source_id", "title", "description", "start_date", "end_date",
            "time", "venue_id", "category", "commune", "source_url", "image_url",
            "price", "venue_name", "address", "contact_phone", "website",
            "status", "confidence", "created_at", "updated_at",
        )
        with self.conn:
            for r in rows:
                vals = _event_to_row(r)
                self.conn.execute(
                    f"INSERT OR REPLACE INTO events ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    vals,
                )

    def _bulk_insert_cinema(self, rows: list[dict]) -> None:
        cols = (
            "id", "title", "duration", "language", "start_date", "end_date",
            "showtimes_json", "image_url", "description", "source_url",
            "status", "confidence", "created_at", "updated_at",
        )
        with self.conn:
            for r in rows:
                vals = _cinema_to_row(r)
                self.conn.execute(
                    f"INSERT OR REPLACE INTO cinema_events ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    vals,
                )

    def _bulk_insert_venues(self, rows: list[dict]) -> None:
        cols = ("id", "name", "commune", "address", "latitude", "longitude", "url", "phone", "source_id")
        with self.conn:
            for r in rows:
                vals = (
                    r.get("id") or r.get("key") or _slug(r.get("name", "")),
                    r.get("name", ""),
                    r.get("commune", "Chamonix"),
                    r.get("address", ""),
                    r.get("latitude"),
                    r.get("longitude"),
                    r.get("url"),
                    r.get("phone"),
                    r.get("source_id", ""),
                )
                self.conn.execute(
                    f"INSERT OR REPLACE INTO venues ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    vals,
                )

    # ---- public CRUD ----

    def upsert_events(self, source_id: str, events: list[dict]) -> int:
        """Replace ALL events for source_id with the given list. Returns count.

        Strategy: DELETE existing rows for source_id, then bulk-INSERT new ones.
        Single transaction; ACID.

        T26: events below the per-source publish threshold are routed to
        review_items (status='open', reason='below_confidence_threshold')
        instead of being published to the events table. Only events at or
        above the threshold appear in `get_events()`. The threshold comes
        from `scripts.sources.get_min_confidence(source_id)`.

        Existing decided (approved/rejected) review_items rows are left
        untouched — operator decisions stand across re-scrapes.
        """
        # Import here to avoid circular import (sources.py imports models.py).
        from scripts.sources import get_min_confidence

        threshold = get_min_confidence(source_id)
        now = datetime.now(timezone.utc).isoformat()

        # Partition events by threshold (precomputed confidence).
        passing: list[dict] = []
        queued: list[dict] = []
        for ev in events:
            try:
                conf = float(ev.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            if conf >= threshold:
                passing.append(ev)
            else:
                queued.append(ev)

        cols = (
            "id", "source_id", "title", "description", "start_date", "end_date",
            "time", "venue_id", "category", "commune", "source_url", "image_url",
            "price", "venue_name", "address", "contact_phone", "website",
            "status", "confidence", "created_at", "updated_at",
        )
        placeholders = ",".join("?" * len(cols))

        with self.conn:
            # 1. Drop all existing published rows for this source.
            self.conn.execute("DELETE FROM events WHERE source_id = ?", (source_id,))

            # 2. Insert the passing events. Also clean up any stale review_items
            # rows for these events (they're above threshold now, no review
            # needed). Only touches status='open' rows; decided (approved/
            # rejected) rows are preserved.
            for r in passing:
                ev_id = r.get("id") or _slug_id(
                    r.get("title", ""), r.get("start_date", "")
                )
                self.conn.execute(
                    """
                    DELETE FROM review_items
                    WHERE source_id = ? AND event_id = ? AND status = 'open'
                    """,
                    (source_id, ev_id),
                )
                vals = list(_event_to_row(r, default_source_id=source_id))
                vals[-1] = now  # updated_at
                self.conn.execute(
                    f"INSERT OR IGNORE INTO events ({','.join(cols)}) VALUES ({placeholders})",
                    vals,
                )

            # 3. Queue below-threshold events to review_items (idempotent).
            for r in queued:
                self._queue_below_threshold(source_id, r, reason="below_confidence_threshold")

        if queued:
            print(
                f"  [t26] {source_id}: threshold={threshold:.2f} "
                f"published={len(passing)} queued_for_review={len(queued)}",
                flush=True,
            )

        return len(events)

    def _queue_below_threshold(self, source_id: str, event: dict, reason: str) -> str:
        """T26 helper: write a single below-threshold event to review_items.

        Idempotent on (source_id, event_id-or-title-hash, reason) via the
        existing deterministic-id scheme in `insert_review_item`. Existing
        decided review_items rows are not overwritten (operator's prior
        decision stands).
        """
        event_id = event.get("id") or _slug_id(
            event.get("title", ""), event.get("start_date", "")
        )
        return self.insert_review_item(
            source_id=source_id,
            event=event,
            reason=reason,
            event_id=event_id,
        )

    # Compatibility alias (some callers used the old name).
    def upsert_events_ungated(self, source_id: str, events: list[dict]) -> int:
        """Bypass T26 threshold routing. Used by tests and the JSON->SQLite
        migration (which preserves whatever data was already on disk).

        Same semantics as the pre-T26 upsert_events: replace-all for the
        source, no review_items routing.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute("DELETE FROM events WHERE source_id = ?", (source_id,))
            cols = (
                "id", "source_id", "title", "description", "start_date", "end_date",
                "time", "venue_id", "category", "commune", "source_url", "image_url",
                "price", "venue_name", "address", "contact_phone", "website",
                "status", "confidence", "created_at", "updated_at",
            )
            for r in events:
                vals = list(_event_to_row(r, default_source_id=source_id))
                vals[-1] = now
                self.conn.execute(
                    f"INSERT OR IGNORE INTO events ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    vals,
                )
        return len(events)

    def upsert_cinema(self, cinema_events: list[dict]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute("DELETE FROM cinema_events")
            cols = (
                "id", "title", "duration", "language", "start_date", "end_date",
                "showtimes_json", "image_url", "description", "source_url",
                "status", "confidence", "created_at", "updated_at",
            )
            for r in cinema_events:
                vals = list(_cinema_to_row(r))
                vals[-1] = now
                self.conn.execute(
                    f"INSERT INTO cinema_events ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    vals,
                )
        return len(cinema_events)

    def upsert_venues(self, venues: list[dict]) -> int:
        with self.conn:
            self.conn.execute("DELETE FROM venues")
            cols = ("id", "name", "commune", "address", "latitude", "longitude", "url", "phone", "source_id")
            for r in venues:
                vals = (
                    r.get("id") or r.get("key") or _slug(r.get("name", "")),
                    r.get("name", ""),
                    r.get("commune", "Chamonix"),
                    r.get("address", ""),
                    r.get("latitude"),
                    r.get("longitude"),
                    r.get("url"),
                    r.get("phone"),
                    r.get("source_id", ""),
                )
                self.conn.execute(
                    f"INSERT INTO venues ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    vals,
                )
        return len(venues)

    def get_events(self, source_id: str | None = None, status: str | None = "published") -> list[dict]:
        q = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if source_id is not None:
            q += " AND source_id = ?"
            params.append(source_id)
        if status is not None:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY start_date, title"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def get_cinema(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM cinema_events ORDER BY start_date, title"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # restore showtimes from JSON blob
            try:
                d["showtimes"] = json.loads(d.pop("showtimes_json") or "{}")
            except json.JSONDecodeError:
                d["showtimes"] = {}
            out.append(d)
        return out

    def get_venues(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM venues ORDER BY name").fetchall()]

    def dedupe_events(self, events: list[dict]) -> list[dict]:
        """T11: canonical cross-source dedup.

        Takes a list of event dicts (already filtered by caller), groups by
        (normalized_title, start_date), returns one event per bucket
        (highest confidence + field completeness wins).
        """
        return dedupe_events(events)

    # ---- T16: venue geocoding ----

    def update_venue_coords(
        self, venue_id: str, latitude: float, longitude: float
    ) -> bool:
        """Set lat/lng on an existing venue. Returns True if a row was updated.

        Idempotent: re-calling with the same coords is a no-op (still returns
        True if the row exists). Used by scripts/geocode_venues.py.
        """
        with self.conn:
            cur = self.conn.execute(
                "UPDATE venues SET latitude = ?, longitude = ? WHERE id = ?",
                (latitude, longitude, venue_id),
            )
        return cur.rowcount > 0

    # ---- T18: curated venue seed ----

    def upsert_venue_curation(self, venue: dict) -> bool:
        """Apply curated fields (postal_code, categories, coords) to a venue.

        Only updates fields that are present and non-null in the input dict;
        leaves other fields untouched. Returns True if a row was updated.

        Categories are stored as a JSON-encoded list. Lat/lng are accepted
        only when both are present and non-zero.

        Idempotent: re-running with the same input is a no-op (still returns
        True if the venue exists).
        """
        vid = venue.get("id")
        if not vid:
            return False

        sets: list[str] = []
        params: list[Any] = []

        lat = venue.get("latitude")
        lng = venue.get("longitude")
        if lat is not None and lng is not None and (lat != 0 or lng != 0):
            sets.extend(["latitude = ?", "longitude = ?"])
            params.extend([lat, lng])

        postal = venue.get("postal_code")
        if postal:
            sets.append("postal_code = ?")
            params.append(postal)

        cats = venue.get("categories")
        if cats:
            sets.append("categories = ?")
            params.append(json.dumps(cats, ensure_ascii=False))

        addr = venue.get("address")
        if addr:
            sets.append("address = ?")
            params.append(addr)

        if not sets:
            return False  # nothing to update

        params.append(vid)
        with self.conn:
            cur = self.conn.execute(
                f"UPDATE venues SET {', '.join(sets)} WHERE id = ?",
                params,
            )
        return cur.rowcount > 0

    def write_build_metadata(self, events_count: int, cinema_count: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO build_metadata (key, value) VALUES ('built_at', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO build_metadata (key, value) VALUES ('events_count', ?)",
                (str(events_count),),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO build_metadata (key, value) VALUES ('cinema_count', ?)",
                (str(cinema_count),),
            )

    def get_build_metadata(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM build_metadata").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def counts(self) -> dict[str, int]:
        return {
            "events": self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "cinema_events": self.conn.execute("SELECT COUNT(*) FROM cinema_events").fetchone()[0],
            "venues": self.conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0],
            "review_items": self.conn.execute("SELECT COUNT(*) FROM review_items").fetchone()[0],
        }

    # ---- T15: review queue (review_items) ----

    def insert_review_item(
        self,
        source_id: str,
        event: dict,
        reason: str,
        event_id: str | None = None,
    ) -> str:
        """Insert (or upsert) a review item for a low-confidence event.

        Idempotent on (source_id, event_id, reason): re-inserting the same
        triple on a later scrape does NOT create a duplicate row IF the
        existing row is still 'open'. If the row was already decided
        (approved/rejected), we don't recreate it — the operator's decision
        stands.

        Returns the stable review-item id.
        """
        import hashlib

        # Stable, deterministic id so re-scrape collisions don't create dups.
        key = "|".join([
            source_id or "",
            event_id or "",
            (event.get("title") or "")[:200],
            (event.get("start_date") or "")[:10],
            reason or "",
        ])
        rid = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

        snapshot_json = json.dumps(event, ensure_ascii=False, sort_keys=True)
        now = datetime.now(timezone.utc).isoformat()
        # T26: extract confidence from event dict (defaults to 0.0 if missing).
        confidence = event.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else 0.0
        except (TypeError, ValueError):
            confidence = 0.0

        with self.conn:
            existing = self.conn.execute(
                "SELECT status FROM review_items WHERE id = ?", (rid,)
            ).fetchone()
            if existing and existing["status"] != "open":
                # Operator already decided; leave it alone.
                return rid
            self.conn.execute(
                """
                INSERT INTO review_items
                    (id, event_id, source_id, reason, event_snapshot,
                     confidence, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'open', ?)
                ON CONFLICT(id) DO UPDATE SET
                    event_snapshot = excluded.event_snapshot,
                    reason         = excluded.reason,
                    source_id      = excluded.source_id,
                    confidence     = excluded.confidence
                """,
                (rid, event_id, source_id, reason, snapshot_json, confidence, now),
            )
        return rid

    def list_review_items(
        self,
        status: str = "open",
        source_id: str | None = None,
        limit: int | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
    ) -> list[dict]:
        """T27: list review items with optional filters.

        Filters:
          - status (open | approved | rejected)
          - source_id (exact match)
          - min_confidence / max_confidence (inclusive range; None = no bound)

        Confidence lives in its own column (T26) so the filter is a simple
        SQL range — no JSON parsing per row.
        """
        sql = "SELECT * FROM review_items WHERE status = ?"
        params: list[Any] = [status]
        if source_id:
            sql += " AND source_id = ?"
            params.append(source_id)
        if min_confidence is not None:
            sql += " AND confidence >= ?"
            params.append(float(min_confidence))
        if max_confidence is not None:
            sql += " AND confidence <= ?"
            params.append(float(max_confidence))
        sql += " ORDER BY confidence ASC, created_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_review_item(self, rid: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM review_items WHERE id = ?", (rid,)
        ).fetchone()
        return dict(row) if row else None

    def review_sources(self) -> list[str]:
        """T27: distinct source_ids present in review_items (for filter UI)."""
        rows = self.conn.execute(
            "SELECT DISTINCT source_id FROM review_items "
            "WHERE source_id IS NOT NULL ORDER BY source_id"
        ).fetchall()
        return [r["source_id"] for r in rows]

    def review_counts_by_status(self) -> dict[str, int]:
        """T27: counts of review_items grouped by status.

        Returns a dict like {'open': 21, 'approved': 0, 'rejected': 0}.
        Missing statuses default to 0.
        """
        rows = self.conn.execute(
            "SELECT status, COUNT(*) FROM review_items GROUP BY status"
        ).fetchall()
        out = {"open": 0, "approved": 0, "rejected": 0}
        for r in rows:
            out[r["status"]] = r["COUNT(*)"]
        return out

    def approve_review_item(
        self,
        rid: str,
        reviewer: str = "operator",
        note: str | None = None,
    ) -> bool:
        """Mark an open review item as approved. Returns True on state change.

        No-op (returns False) if the item is missing or already decided.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE review_items
                SET status = 'approved', reviewed_by = ?, reviewed_at = ?,
                    notes = COALESCE(?, notes)
                WHERE id = ? AND status = 'open'
                """,
                (reviewer, now, note, rid),
            )
        return cur.rowcount > 0

    def reject_review_item(
        self,
        rid: str,
        reviewer: str = "operator",
        note: str | None = None,
    ) -> bool:
        """Mark an open review item as rejected. Note is required in practice;
        callers (the CLI) enforce that. Returns True on state change.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE review_items
                SET status = 'rejected', reviewed_by = ?, reviewed_at = ?,
                    notes = COALESCE(?, notes)
                WHERE id = ? AND status = 'open'
                """,
                (reviewer, now, note, rid),
            )
        return cur.rowcount > 0

    def close(self) -> None:
        self.conn.close()


# ----- helpers --------------------------------------------------------------

def _event_to_row(r: dict, default_source_id: str | None = None) -> tuple:
    """Project an event dict to a positional tuple matching the events table."""
    return (
        r.get("id") or _slug_id(r.get("title", ""), r.get("start_date", "")),
        r.get("source_id") or default_source_id or "chamonix_com",
        r.get("title", ""),
        r.get("description", "") or "",
        r.get("start_date"),
        r.get("end_date"),
        r.get("time"),
        r.get("venue_id"),
        r.get("category", "other"),
        r.get("commune", "Chamonix"),
        r.get("source_url"),
        r.get("image_url"),
        r.get("price"),
        r.get("venue_name"),
        r.get("address"),
        r.get("contact_phone"),
        r.get("website"),
        r.get("status", "published"),
        r.get("confidence", 1.0),
        r.get("created_at") or datetime.now(timezone.utc).isoformat(),
        r.get("updated_at") or datetime.now(timezone.utc).isoformat(),
    )


def _cinema_to_row(r: dict) -> tuple:
    """Project a cinema dict to a positional tuple matching the cinema_events table."""
    showtimes = r.get("showtimes", {})
    showtimes_json = json.dumps(showtimes, ensure_ascii=False) if isinstance(showtimes, dict) else "{}"
    return (
        r.get("id") or _slug(r.get("title", "")),
        r.get("title", ""),
        r.get("duration"),
        r.get("language"),
        r.get("start_date"),
        r.get("end_date"),
        showtimes_json,
        r.get("image_url"),
        r.get("description", ""),
        r.get("source_url"),
        r.get("status", "published"),
        r.get("confidence", 1.0),
        r.get("created_at") or datetime.now(timezone.utc).isoformat(),
        r.get("updated_at") or datetime.now(timezone.utc).isoformat(),
    )


def _slug(s: str) -> str:
    import re
    s = (s or "").lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-") or "unnamed"


def _slug_id(title: str, start_date: str) -> str:
    date_part = (start_date or "")[:10]
    return f"{_slug(title)}-{date_part}" if date_part else _slug(title)


# ----- module-level convenience -----

_default: Storage | None = None


def get_storage() -> Storage:
    """Module-level singleton. Cheap to call repeatedly."""
    global _default
    if _default is None:
        _default = Storage()
    return _default
