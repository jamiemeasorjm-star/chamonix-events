#!/usr/bin/env python3
"""durable_check — stand-alone verification for the durable storage path.

Proves (using ONLY an isolated temp DB copy under /root/chx-durable):
  1. healthy rescrape:  insert 2 events, re-upsert the same 2 -> still 2
     active, 0 tombstoned.
  2. missing event:     upsert A+B, then upsert only A -> A active, B
     tombstoned (absent_since set) and NOT deleted.
  3. protected:         create a `curated` row, run
     upsert_events_durable('chamonix_com', ...) -> curated row untouched.
  4. tombstoned excluded: get_events(status='published') does not include
     tombstoned rows (DURABLE_DEFAULT=True, per FIX 2).
  5. FIX 2: get_events tombstone filter present when flag True, absent when
     False (toggling DURABLE_DEFAULT).
  6. FIX 1: venue accent/space drift maps to the same durable row key.
  7. FIX 3: a legacy row_key IS NULL row's translations survive the first
     durable run and it is not tombstoned while still present.
  8. FIX 4: a tombstone older than the threshold is purged by clean_past's
     helper; a newer one is kept.

Exits 0 if all checks pass, 1 otherwise. Prints a progress report.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from scripts.storage import Storage
from scripts.storage import PROTECTED_SOURCES
from scripts.storage import DURABLE_DEFAULT
from scripts.storage import _event_row_key
import scripts.storage as storage_mod
from scripts import clean_past


def fresh_db() -> str:
    """Create a brand-new temp DB under /root/chx-durable, pre-seeded so the
    JSON->SQLite migration never runs against any data dir (avoids ever
    reading the LIVE data files). Returns the temp DB path."""
    tmpdir = tempfile.mkdtemp(prefix="durable_check_", dir=str(WORKTREE))
    db_path = os.path.join(tmpdir, "side.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS build_metadata (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO build_metadata (key, value) VALUES (?, ?)",
            ("migrated_from_json", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def main() -> int:
    checks = []
    failures = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append(name)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
        if not ok:
            failures.append((name, detail))

    # ---- Scenario 1: healthy rescrape ----
    print("\nScenario 1: healthy rescrape (re-upsert same 2 -> still 2 active)")
    db1 = fresh_db()
    st = Storage(db1)
    ev_a = {"title": "Concert du Film", "start_date": "2026-08-10",
            "venue_name": "Cinéma Le Vagabond", "description": "original"}
    ev_b = {"title": "Conférence Montagne", "start_date": "2026-08-11",
            "venue_name": "Auditorium", "description": "original"}
    st.upsert_events_durable("chamonix_com", [ev_a, ev_b])
    # re-upsert the identical pair (same content)
    st.upsert_events_durable("chamonix_com", [ev_a, ev_b])
    active = st.get_events(source_id="chamonix_com", status="published")
    count = st.conn.execute(
        "SELECT COUNT(*) FROM events WHERE source_id='chamonix_com'"
    ).fetchone()[0]
    tomb = st.conn.execute(
        "SELECT COUNT(*) FROM events WHERE source_id='chamonix_com' "
        "AND absent_since IS NOT NULL"
    ).fetchone()[0]
    check("1a rescrape keeps 2 active rows", len(active) == 2, f"active={len(active)}")
    check("1b no rows tombstoned", tomb == 0, f"tombstoned={tomb}")
    check("1c exactly 2 total rows (no dupes)", count == 2, f"total={count}")
    st.close()

    # ---- Scenario 2: missing event -> tombstone, not delete ----
    print("\nScenario 2: missing event (upsert A+B, then only A)")
    # FIX 2: the tombstone-exclusion in get_events is gated behind the opt-in
    # flag, so this scenario (which expects tombstoned rows hidden) runs with
    # DURABLE_DEFAULT=True.
    storage_mod.DURABLE_DEFAULT = True
    db2 = fresh_db()
    st = Storage(db2)
    st.upsert_events_durable("chamonix_net", [ev_a, ev_b])
    st.upsert_events_durable("chamonix_net", [ev_a])  # B disappears
    active = st.get_events(source_id="chamonix_net", status="published")
    row_b = st.conn.execute(
        "SELECT absent_since FROM events WHERE source_id='chamonix_net' "
        "AND title LIKE '%Conférence%'"
    ).fetchone()
    row_b_deleted = st.conn.execute(
        "SELECT COUNT(*) FROM events WHERE source_id='chamonix_net' "
        "AND title LIKE '%Conférence%'"
    ).fetchone()[0]
    titles = sorted((r["title"] for r in active))
    check("2a only A returned active", titles == ["Concert du Film"], f"titles={titles}")
    check("2b B row still exists (NOT deleted)", row_b_deleted == 1,
          f"B rows={row_b_deleted}")
    check("2c B tombstoned (absent_since set)", row_b is not None and row_b["absent_since"] is not None,
          f"absent_since={row_b['absent_since'] if row_b else None}")
    # resurrect: upsert A+B again -> B back, absent_since cleared
    st.upsert_events_durable("chamonix_net", [ev_a, ev_b])
    row_b2 = st.conn.execute(
        "SELECT absent_since FROM events WHERE source_id='chamonix_net' "
        "AND title LIKE '%Conférence%'"
    ).fetchone()
    active2 = st.get_events(source_id="chamonix_net", status="published")
    check("2d B resurrected (absent_since cleared)", row_b2 is not None and row_b2["absent_since"] is None,
          f"absent_since={row_b2['absent_since'] if row_b2 else None}")
    check("2e both active again after re-upsert", len(active2) == 2, f"active={len(active2)}")
    st.close()

    # ---- Scenario 3: protected source ----
    print("\nScenario 3: protected source (curated untouched)")
    db3 = fresh_db()
    st = Storage(db3)
    curated = {"title": "Événement Curé", "start_date": "2026-09-01",
               "venue_name": "Office", "description": "hand-curated",
               "source_id": "curated", "status": "published"}
    st.conn.execute(
        "INSERT INTO events (id, source_id, title, start_date, venue_name, "
        "description, status) VALUES (?,?,?,?,?,?,?)",
        ("cur_1", "curated", curated["title"], curated["start_date"],
         curated["venue_name"], curated["description"], "published"),
    )
    st.conn.commit()
    st.upsert_events_durable("chamonix_com", [ev_a])
    row = st.conn.execute(
        "SELECT title, description, status FROM events WHERE source_id='curated'"
    ).fetchone()
    check("3a curated row still present", row is not None)
    check("3b curated content unchanged",
          row is not None and row["title"] == "Événement Curé"
          and row["description"] == "hand-curated",
          f"title={row['title'] if row else None}")
    check("3c protected set matches brief",
          PROTECTED_SOURCES == {"curated", "manual_submission"})
    st.close()

    # ---- Scenario 4: tombstoned excluded from published ----
    print("\nScenario 4: tombstoned rows excluded from get_events(published)")
    storage_mod.DURABLE_DEFAULT = True  # FIX 2: filter is opt-in
    db4 = fresh_db()
    st = Storage(db4)
    st.upsert_events_durable("chamonix_com", [ev_a, ev_b])
    st.upsert_events_durable("chamonix_com", [ev_a])  # B tombstoned
    published = st.get_events(status="published")
    b_in_published = any(B and "Conférence" in B for B in
                         (e["title"] for e in published))
    check("4a tombstoned row excluded from published", not b_in_published)
    check("4b active row still published", any(
        e["title"] == "Concert du Film" for e in published))
    st.close()

    # ---- Scenario 5 (FIX 2): get_events tombstone filter is opt-in ----
    print("\nScenario 5 (FIX 2): get_events tombstone filter gated by DURABLE_DEFAULT")
    db5 = fresh_db()
    st = Storage(db5)
    st.upsert_events_durable("chamonix_com", [ev_a, ev_b])
    st.upsert_events_durable("chamonix_com", [ev_a])  # B tombstoned
    storage_mod.DURABLE_DEFAULT = False
    pub_off = st.get_events(status="published")
    b_off = any("Conférence" in e["title"] for e in pub_off)
    storage_mod.DURABLE_DEFAULT = True
    pub_on = st.get_events(status="published")
    b_on = any("Conférence" in e["title"] for e in pub_on)
    storage_mod.DURABLE_DEFAULT = False
    check("5a filter ABSENT when flag False (tombstone returned)",
          b_off, f"tombstone_visible={b_off}")
    check("5b filter PRESENT when flag True (tombstone hidden)",
          not b_on, f"tombstone_hidden={not b_on}")
    st.close()

    # ---- Scenario 6 (FIX 1): venue accent/space drift -> stable key ----
    print("\nScenario 6 (FIX 1): venue normalized in durable row key")
    k_acc = _event_row_key("src", {"title": "Concert", "start_date": "2026-08-10",
                                   "venue_name": "Cinéma Le Vagabond"})
    k_plain = _event_row_key("src", {"title": "Concert", "start_date": "2026-08-10",
                                     "venue_name": "Cinema Le Vagabond"})
    check("6a accent drift maps to same key", k_acc == k_plain,
          f"{k_acc!r} vs {k_plain!r}")
    check("6b venue normalized (accent stripped) in key",
          k_acc.endswith("cinema le vagabond"), k_acc)
    db6 = fresh_db()
    st = Storage(db6)
    st.upsert_events_durable("chamonix_com", [{"title": "Concert",
        "start_date": "2026-08-10", "venue_name": "Cinéma Le Vagabond"}])
    st.upsert_events_durable("chamonix_com", [{"title": "Concert",
        "start_date": "2026-08-10", "venue_name": "Cinema Le Vagabond"}])
    merged = st.conn.execute(
        "SELECT COUNT(*) FROM events WHERE source_id='chamonix_com'"
    ).fetchone()[0]
    check("6c venue drift merges into one row (no dup)", merged == 1,
          f"rows={merged}")
    st.close()

    # ---- Scenario 7 (FIX 3): legacy row_key NULL backfill preserves tx ----
    print("\nScenario 7 (FIX 3): legacy row_key backfill preserves translations")
    db7 = fresh_db()
    st = Storage(db7)
    st.conn.execute(
        "INSERT INTO events (id, source_id, title, start_date, venue_name, "
        "description, title_en, description_en, status) VALUES (?,?,?,?,?,?,?,?,?)",
        ("legacy_1", "chamonix_com", "Atelier Dessin", "2026-09-01",
         "Espace", "legacy", "Drawing Workshop", "English desc", "published"),
    )
    st.conn.commit()
    rk_before = st.conn.execute(
        "SELECT row_key FROM events WHERE id='legacy_1'"
    ).fetchone()["row_key"]
    check("7a legacy row starts with NULL row_key", rk_before is None)
    incoming = {"title": "Atelier Dessin", "start_date": "2026-09-01",
                "venue_name": "Espace", "description": "legacy"}
    st.upsert_events_durable("chamonix_com", [incoming])  # first durable run
    row7 = st.conn.execute(
        "SELECT row_key, absent_since, title_en, description_en "
        "FROM events WHERE id='legacy_1'"
    ).fetchone()
    check("7b legacy row key backfilled", row7 is not None and row7["row_key"] is not None,
          f"row_key={row7['row_key'] if row7 else None}")
    check("7c legacy row NOT tombstoned (still present)",
          row7 is not None and row7["absent_since"] is None,
          f"absent_since={row7['absent_since'] if row7 else None}")
    check("7d translation title_en preserved",
          row7 is not None and row7["title_en"] == "Drawing Workshop",
          f"title_en={row7['title_en'] if row7 else None}")
    check("7e translation description_en preserved",
          row7 is not None and row7["description_en"] == "English desc",
          f"description_en={row7['description_en'] if row7 else None}")
    # re-run is a no-op (idempotent backfill)
    st.upsert_events_durable("chamonix_com", [incoming])
    still = st.conn.execute(
        "SELECT COUNT(*) FROM events WHERE id='legacy_1' AND absent_since IS NULL"
    ).fetchone()[0]
    check("7f backfill/upsert idempotent on re-run", still == 1, f"live_rows={still}")
    st.close()

    # ---- Scenario 8 (FIX 4): tombstone expiry in clean_past ----
    print("\nScenario 8 (FIX 4): clean_past purges old tombstones")
    from datetime import datetime, timedelta, timezone as _tz
    db8 = fresh_db()
    st_old = Storage(db8)
    old_ts = (datetime.now(_tz.utc) - timedelta(days=40)).isoformat()
    new_ts = (datetime.now(_tz.utc) - timedelta(days=5)).isoformat()
    st_old.conn.execute(
        "INSERT INTO events (id, source_id, title, start_date, absent_since) "
        "VALUES (?,?,?,?,?)",
        ("t_old", "chamonix_com", "Old Tombstone", "2026-01-01", old_ts),
    )
    st_old.conn.execute(
        "INSERT INTO events (id, source_id, title, start_date, absent_since) "
        "VALUES (?,?,?,?,?)",
        ("t_new", "chamonix_com", "New Tombstone", "2026-01-01", new_ts),
    )
    st_old.conn.commit()
    storage_mod._default = None
    os.environ["CHAMONIX_DB"] = db8
    removed = clean_past.clean_tombstones()
    left_ids = [r["id"] for r in st_old.conn.execute(
        "SELECT id FROM events WHERE absent_since IS NOT NULL"
    ).fetchall()]
    check("8a old tombstone (>30d) purged", removed == 1, f"removed={removed}")
    check("8b newer tombstone (5d) kept", left_ids == ["t_new"], f"left={left_ids}")
    st_old.close()

    # ---- Final confirmation ----
    storage_mod.DURABLE_DEFAULT = False
    check("c DURABLE_DEFAULT still defaults to False",
          DURABLE_DEFAULT is False and storage_mod.DURABLE_DEFAULT is False)

    print("\n" + "=" * 50)
    print(f"Ran {len(checks)} checks: {len(checks) - len(failures)} passed, "
          f"{len(failures)} failed")
    if failures:
        for name, detail in failures:
            print(f"  FAILED: {name}  {detail}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
