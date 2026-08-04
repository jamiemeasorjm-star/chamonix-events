#!/usr/bin/env python3
"""cinema-merge tests (BRIEF4): storage.enrich_cinema + legacy cleanup.

Runs ONLY against a fresh seeded copy (temp DB) — the live DB is never
opened/touched. Verifies that:
  1. enrich_cinema backfills missing image_url/description on matching
     cinema_events rows (including an accented variant matched by normalized
     title).
  2. Existing populated values on cinema_events are preserved (no overwrite).
  3. No cinema_events rows are deleted.
  4. The `events` table is untouched by enrich_cinema (count unchanged, no
     inserts/updates/deletes).
  5. The legacy allocine_vox cleanup removes ONLY source_id='allocine_vox' +
     category='Cinema' rows from `events`, and no others; idempotent re-run
     removes 0.

Run: CHAMONIX_DB=<tmp copy> python3 scripts/cinema_check.py
"""
from __future__ import annotations
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.storage import Storage

FAILURES: list[str] = []
PASSES: int = 0


def check(cond: bool, msg: str) -> None:
    global PASSES
    if cond:
        PASSES += 1
        print(f"  [PASS] {msg}")
    else:
        FAILURES.append(msg)
        print(f"  [FAIL] {msg}")


def make_db() -> tuple[Storage, str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    # Mark as already-migrated so Storage() does NOT read/import live JSON
    # data into this isolated seeded copy.
    import sqlite3 as _sqlite3
    _c = _sqlite3.connect(path)
    _c.execute("CREATE TABLE IF NOT EXISTS build_metadata (key TEXT PRIMARY KEY, value TEXT)")
    _c.execute("INSERT OR REPLACE INTO build_metadata (key, value) VALUES ('migrated_from_json', '1')")
    _c.commit()
    _c.close()
    storage = Storage(path)
    # Seed cinema_events: matching films with EMPTY image_url/description.
    with storage.conn:
        storage.conn.executemany(
            "INSERT INTO cinema_events (id, title, image_url, description, status) "
            "VALUES (?, ?, ?, ?, 'published')",
            [
                ("c1", "LE COMTE DE MONTE-CRISTO", "", "", ),
                ("c2", "Le Comte de Monte-Cristo", "", "", ),  # accent-free variant
                ("c3", "UN PETIT TRUC EN PLUS", "", "", ),
                ("c4", "ÉMILIA PÉREZ", "", "", ),  # accented variant
            ],
        )
        # Seed an already-populated row (must be preserved, never overwritten).
        storage.conn.execute(
            "INSERT INTO cinema_events (id, title, image_url, description, status) "
            "VALUES ('c5', 'ALIEN: ROMULUS', 'https://img.keep/alien.jpg', "
            "'Existing description', 'published')"
        )
        # Seed `events` rows: one allocine_vox Cinema (cleanup target), one
        # allocine_vox non-Cinema (must survive), one other-source Cinema
        # (must survive).
        storage.conn.executemany(
            "INSERT INTO events (id, source_id, title, category, status) "
            "VALUES (?, ?, ?, ?, 'published')",
            [
                ("e1", "allocine_vox", "Film X", "Cinema"),
                ("e2", "allocine_vox", "Film Y", "Music"),
                ("e3", "chamonix_com", "Film Z", "Cinema"),
            ],
        )
    return storage, path


def main() -> None:
    storage, path = make_db()
    try:
        print("--- Before enrich ---")
        events_before = storage.get_events()
        cinema_before = storage.get_cinema()
        events_before_ids = {r["id"] for r in events_before}
        events_before_by_id = {r["id"]: dict(r) for r in events_before}

        # Run enrich_cinema with matching films. The accented variant
        # ("ÉMILIA PÉREZ") normalizes to the same key as the accented seed
        # title. Non-matching films are ignored.
        movies = [
            {"title": "LE COMTE DE MONTE-CRISTO",
             "image_url": "https://img.acsta/monte.jpg",
             "description": "D'après le roman d'Alexandre Dumas.",
             "title_en": "The Count of Monte Cristo"},
            {"title": "Emilia Perez",  # acecntless -> matches accented seed via normalize
             "image_url": "https://img.acsta/emilia.jpg",
             "description": "Comédie musicale."},
            {"title": "UN PETIT TRUC EN PLUS", "image_url": "https://img/truc.jpg"},
            {"title": "TITRE INCONNU", "image_url": "https://img/nope.jpg",
             "description": "Should NOT match any row."},
        ]
        n = storage.enrich_cinema(movies)
        print(f"--- enrich_cinema returned {n} ---")

        cinema = {r["id"]: r for r in storage.get_cinema()}
        # 1. Backfill on matching rows.
        check(cinema["c1"]["image_url"] == "https://img.acsta/monte.jpg",
              "c1 image_url backfilled")
        check(cinema["c1"]["description"].startswith("D'après"),
              "c1 description backfilled")
        check(cinema["c1"]["title_en"] == "The Count of Monte Cristo",
              "c1 title_en backfilled")
        # 2. Accented variant matched via normalized title (seed c4 "ÉMILIA PÉREZ").
        check(cinema["c4"]["image_url"] == "https://img.acsta/emilia.jpg",
              "c4 accented variant matched + image_url backfilled")
        check(cinema["c4"]["description"] == "Comédie musicale.",
              "c4 accented variant description backfilled")
        # c3 got image_url only (no description supplied).
        check(cinema["c3"]["image_url"] == "https://img/truc.jpg",
              "c3 image_url backfilled")
        # 3. Existing populated values preserved (never overwritten).
        check(cinema["c5"]["image_url"] == "https://img.keep/alien.jpg",
              "c5 existing image_url preserved (not overwritten)")
        check(cinema["c5"]["description"] == "Existing description",
              "c5 existing description preserved (not overwritten)")
        # 4. No cinema_events rows deleted.
        check(len(cinema) == len(cinema_before),
              f"no cinema_events rows deleted ({len(cinema)})")
        # 5. events table untouched by enrich_cinema.
        events_after = storage.get_events()
        check(len(events_after) == len(events_before),
              "events count unchanged after enrich")
        check({r["id"] for r in events_after} == events_before_ids,
              "events ids unchanged after enrich")
        unchanged_vals = all(
            dict(r) == events_before_by_id[r["id"]] for r in events_after
        )
        check(unchanged_vals,
              "no events rows were added/changed by enrich_cinema")

        # 6. Legacy cleanup: only allocine_vox + Cinema rows removed.
        print("--- legacy cleanup ---")
        from scripts import allocine_vox
        removed = allocine_vox._cleanup_legacy_allocine_cinema(storage)
        check(removed == 1, f"cleanup removed exactly 1 row (got {removed})")

        storage2 = Storage(path)  # fresh connection to confirm idempotent
        rows = storage2.get_events()
        ids = {r["id"] for r in rows}
        check("e1" not in ids, "allocine_vox Cinema row e1 removed")
        check("e2" in ids, "allocine_vox non-Cinema row e2 preserved")
        check("e3" in ids, "other-source Cinema row e3 preserved")

        # 7. Idempotent: second cleanup removes 0.
        removed2 = allocine_vox._cleanup_legacy_allocine_cinema(storage2)
        check(removed2 == 0, f"cleanup idempotent (second run removed {removed2})")
        storage2.close()

        print("\n=== SUMMARY ===")
        print(f"Assertions passed: {PASSES}")
        if FAILURES:
            print(f"FAILURES ({len(FAILURES)}):")
            for f in FAILURES:
                print(f"  - {f}")
            sys.exit(1)
        print("ALL ASSERTIONS PASSED")
    finally:
        storage.close()
        try:
            os.unlink(path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
