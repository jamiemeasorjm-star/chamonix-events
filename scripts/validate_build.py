#!/usr/bin/env python3
"""Read-only build/site gate for the Chamonix harness (Phase 2).

Reads ONLY (SELECT / mode=ro files). Never writes, deletes or modifies
anything. Checks G5: build freshness, event/page sanity (orphan detection),
cinema completeness, plus an informational dead-review-UI check.

Prints PASS/FAIL per gate. Exit codes (bitmask, non-zero = gate failed):
    0 = all gates pass
    1 = build freshness failed
    2 = orphans/slug-set mismatch failed
    4 = event-count sanity failed
    8 = cinema completeness failed
"""

import json
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configurable thresholds / constants
# ---------------------------------------------------------------------------
BUILD_AGE_HOURS = 30.0          # max allowed build age in hours
ORPHAN_CAP = 15                 # cap for orphan listing

WORKTREE = Path("/docker/hermes-agent-2bpx/data/chamonix-events")
LIVE_PATH = Path("/docker/hermes-agent-2bpx/data/chamonix-events")
LIVE_DB = "/docker/hermes-agent-2bpx/data/chamonix-events/data/chamonix.db"
DEFAULT_DB = "/docker/hermes-agent-2bpx/data/chamonix-events/data/chamonix.db"

LASTBUILD_JSON = WORKTREE / "data" / "last_build.json"
EVENTS_DIR = WORKTREE / "events"
REVIEW_HTML = WORKTREE / "review.html"
REVIEW_TEMPLATE = WORKTREE / "review.html.template"


def db_path() -> str:
    p = os.environ.get("CHAMONIX_DB") or DEFAULT_DB
    return p


def connect_ro():
    con = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def slugify(text: str, date_suffix: str | None = None) -> str:
    """Mirror build.py slugify so orphan detection matches the real build."""
    text = str(text).lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = re.sub(r"[\u0300-\u036f]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    text = re.sub(r"-+", "-", text)
    text = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", text)
    if date_suffix and len(date_suffix) >= 7:
        short_date = date_suffix[:7].replace("-", "")
        text = f"{text[:60]}-{short_date}"
    return text[:80] or "event"


def current_slug_set(cur) -> tuple[set[str], dict]:
    """Compute the set of expected /events/<slug>.html basenames from the DB.

    Matches build.py generate_event_pages(merged + cinema), including the
    collision suffixing. Returns (slug_set, info)."""
    def fetch(table, status_col="status"):
        return cur.execute(
            f"SELECT id, COALESCE(start_date,end_date,'') AS d, title FROM {table} "
            f"WHERE status='published'"
        ).fetchall()

    used: set[str] = set()
    info = {"events": 0, "cinema": 0}
    for table in ("events", "cinema_events"):
        for r in fetch(table):
            base = slugify(r["id"], date_suffix=r["d"])
            slug = base
            if slug in used:
                n = 2
                while f"{base}-{n}" in used:
                    n += 1
                slug = f"{base}-{n}"
            used.add(slug)
            info[table if table == "events" else "cinema"] += 1
    return used, info


def parse_iso(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def read_last_build() -> dict:
    data = {}
    if LASTBUILD_JSON.exists():
        try:
            data = json.loads(LASTBUILD_JSON.read_text())
        except Exception:
            data = {}
    return data


def gate_build(cur) -> tuple[bool, str]:
    lines = []
    ok = True
    exit_bit = 0

    # ---- Build freshness ----
    lb = read_last_build()
    lb_built = parse_iso(lb.get("built_at"))
    src_desc = "data/last_build.json"
    if lb_built is None:
        # Fall back to DB build_metadata (single source of truth)
        row = cur.execute(
            "SELECT value FROM build_metadata WHERE key='built_at'"
        ).fetchone()
        if row:
            lb_built = parse_iso(row["value"])
            src_desc = "DB build_metadata"
    now = datetime.now(timezone.utc)
    if lb_built is None:
        lines.append("  build freshness: NO build timestamp found (last_build.json missing and no build_metadata)")
        ok = False
        exit_bit |= 1
    else:
        if lb_built.tzinfo is None:
            lb_built = lb_built.replace(tzinfo=timezone.utc)
        age = max(0.0, (now - lb_built).total_seconds() / 3600.0)
        fresh = age <= BUILD_AGE_HOURS
        lines.append(f"  build freshness: built_at={lb_built.isoformat()} (from {src_desc}), age={age:.2f}h (target < {BUILD_AGE_HOURS:.0f}h)")
        if not fresh:
            ok = False
            exit_bit |= 1

    # ---- Event count sanity ----
    db_events = cur.execute(
        "SELECT COUNT(*) FROM events WHERE status='published'"
    ).fetchone()[0]
    lb_events = lb.get("events")
    if lb_events is None:
        row = cur.execute(
            "SELECT value FROM build_metadata WHERE key='events_count'"
        ).fetchone()
        lb_events = int(row["value"]) if row else None
    if lb_events is None:
        lines.append(f"  event count: DB={db_events}, last_build=unknown")
    else:
        matched = db_events == lb_events
        lines.append(f"  event count: DB={db_events}, last_build={lb_events} -> {'MATCH' if matched else 'MISMATCH'}")
        if not matched:
            ok = False
            exit_bit |= 4

    # ---- Orphan detection (event pages not in current slug set) ----
    slug_set, info = current_slug_set(cur)
    disks = set()
    if EVENTS_DIR.is_dir():
        disks = {p.name[: -len(".html")] for p in EVENTS_DIR.glob("*.html")}
    orphans = sorted(disks - slug_set)
    lines.append(f"  event pages on disk: {len(disks)}; expected slug set: {len(slug_set)} "
                 f"(events={info['events']}, cinema={info['cinema']})")
    if orphans:
        lines.append(f"  ORPHANS ({len(orphans)}): " + ", ".join(orphans[:ORPHAN_CAP])
                     + (f" …and {len(orphans) - ORPHAN_CAP} more" if len(orphans) > ORPHAN_CAP else ""))
        ok = False
        exit_bit |= 2
    else:
        lines.append("  ORPHANS: 0 (all on-disk event pages are in the current slug set)")

    # ---- Cinema completeness ----
    cin_total = cur.execute(
        "SELECT COUNT(*) FROM cinema_events WHERE status='published'"
    ).fetchone()[0]
    today = datetime.now(timezone.utc).date().isoformat()
    cin_stale = cur.execute(
        "SELECT COUNT(*) FROM cinema_events WHERE status='published' AND end_date IS NOT NULL AND end_date < ?",
        (today,),
    ).fetchone()[0]
    cin_no_media = cur.execute(
        "SELECT COUNT(*) FROM cinema_events WHERE status='published' AND (image_url IS NULL OR trim(image_url)='' OR description IS NULL OR trim(description)='')"
    ).fetchone()[0]
    lines.append(f"  cinema completeness: films={cin_total}, stale={cin_stale}, missing poster/description={cin_no_media}")
    if cin_total == 0:
        lines.append("  CINEMA IS SILENTLY EMPTY")
        ok = False
        exit_bit |= 8

    return ok, exit_bit, "\n".join(lines)


def dead_review_check(cur) -> str:
    exists = REVIEW_HTML.exists() or (REVIEW_TEMPLATE.exists() and not REVIEW_HTML.exists())
    review_tmpl = REVIEW_TEMPLATE.exists()
    n_rows = cur.execute("SELECT COUNT(*) FROM review_items").fetchone()[0]
    return (
        "GATE G6 (informational): dead-review-UI check\n"
        f"  review.html present: {REVIEW_HTML.exists()}\n"
        f"  review.html.template present: {review_tmpl}\n"
        f"  review_items rows: {n_rows}\n"
        f"  (the review UI is obsolete; maintained for reference only)"
    )


def main() -> int:
    con = connect_ro()
    cur = con.cursor()

    build_ok, bits, txt = gate_build(cur)
    status = "PASS" if build_ok else "FAIL"
    print(f"GATE G5: {status}")
    print(txt)
    print()
    print(dead_review_check(cur))
    print()

    exit_code = bits if build_ok else bits
    print(f"OVERALL: {'ALL GATES PASS' if exit_code == 0 else 'ONE OR MORE GATES FAILED'} (exit={exit_code})")
    con.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
