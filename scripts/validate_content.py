#!/usr/bin/env python3
"""Read-only content gate for the Chamonix harness (Phase 2).

Reads ONLY from the DB (SELECT / mode=ro). Never writes, deletes or modifies
anything. Computes G1 (content), G2 (cinema) and G3 (map) coverage metrics and
prints PASS/FAIL per gate.

Exit codes (bitmask, non-zero = at least one gate failed):
    0 = all gates pass
    1 = G1 (content) failed
    2 = G2 (cinema) failed
    4 = G3 (map) failed
"""

import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configurable thresholds (module-level constants)
# ---------------------------------------------------------------------------
G1_TITLE_START_PCT = 100.0   # events with title + start_date
G1_VENUE_DESC_PCT = 95.0     # events with non-empty venue_name AND description
G1_IMAGE_PCT = 95.0          # events with image_url
G2_IMAGE_PCT = 100.0         # films with image_url
G2_DESC_PCT = 100.0          # films with description
G3_MAP_PCT = 70.0            # active events' venue_name resolves to lat/lng
CAP = 15                     # cap for lists of missing items

# Default DB path (used if CHAMONIX_DB is not set) — the LIVE DB. This sensor
# is the production content monitor: it opens the DB strictly read-only
# (mode=ro), so reading the live DB is safe (no writes possible). Set
# CHAMONIX_DB to any path to point it elsewhere (e.g. a seeded copy for tests).
DEFAULT_DB = "/docker/hermes-agent-2bpx/data/chamonix-events/data/chamonix.db"


def db_path() -> str:
    """Return the DB to open read-only, honouring CHAMONIX_DB env var."""
    p = os.environ.get("CHAMONIX_DB") or DEFAULT_DB
    return p


def connect_ro():
    con = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def pct(num, den):
    return (100.0 * num / den) if den else 100.0


def cap_list(items, label=None):
    """Return formatted capped list: first CAP + '...and N more'."""
    if not items:
        return ""
    shown = items[:CAP]
    out = "; ".join(shown)
    if len(items) > CAP:
        out += f"  …and {len(items) - CAP} more"
    return out


def is_blank(v):
    return v is None or str(v).strip() == ""


# ---------------------------------------------------------------------------
# G1 — Content coverage
# ---------------------------------------------------------------------------
def gate_content(cur) -> tuple[bool, str]:
    total = cur.execute(
        "SELECT COUNT(*) FROM events WHERE status='published'"
    ).fetchone()[0]

    def prop(cond):
        return cur.execute(
            f"SELECT COUNT(*) FROM events WHERE status='published' AND ({cond})"
        ).fetchone()[0]

    n_title_start = prop("title IS NOT NULL AND trim(title)!='' AND start_date IS NOT NULL AND trim(start_date)!=''")
    n_src = prop("source_url IS NOT NULL AND trim(source_url)!=''")
    n_vd = prop("venue_name IS NOT NULL AND trim(venue_name)!='' AND description IS NOT NULL AND trim(description)!=''")
    n_img = prop("image_url IS NOT NULL AND trim(image_url)!=''")

    p_ts = pct(n_title_start, total)
    p_src = pct(n_src, total)
    p_vd = pct(n_vd, total)
    p_img = pct(n_img, total)

    ok = (p_ts >= G1_TITLE_START_PCT and p_src >= 100.0
          and p_vd >= G1_VENUE_DESC_PCT
          and p_img >= G1_IMAGE_PCT)

    lines = [
        f"  G1 events (published): {total}",
        f"  title+start_date coverage: {p_ts:.1f}% (target {G1_TITLE_START_PCT:.0f}%)",
        f"  source_url coverage: {p_src:.1f}% (target 100.0%)",
        f"  venue_name+description coverage: {p_vd:.1f}% (target {G1_VENUE_DESC_PCT:.0f}%)",
        f"  image_url coverage: {p_img:.1f}% (target {G1_IMAGE_PCT:.0f}%)",
    ]

    # Per-source coverage
    lines.append("  per-source coverage (venue/description/image):")
    sources = [r[0] for r in cur.execute(
        "SELECT DISTINCT source_id FROM events WHERE status='published' ORDER BY source_id"
    ).fetchall()]
    for src in sources:
        def scol(cond):
            return cur.execute(
                "SELECT COUNT(*) FROM events WHERE status='published' AND source_id=? AND ("
                + cond + ")", (src,)).fetchone()[0]
        s_total = cur.execute(
            "SELECT COUNT(*) FROM events WHERE status='published' AND source_id=?", (src,)
        ).fetchone()[0]
        s_vd = scol("venue_name IS NOT NULL AND trim(venue_name)!='' AND description IS NOT NULL AND trim(description)!=''")
        s_img = scol("image_url IS NOT NULL AND trim(image_url)!=''")
        lines.append(
            f"    {src}: n={s_total} vd={pct(s_vd, s_total):.1f}% img={pct(s_img, s_total):.1f}%"
        )

    # Lists of missing items (title+start always complete so only vd/img)
    lines.append("  events missing venue or description:")
    rows = cur.execute(
        "SELECT id,title FROM events WHERE status='published' AND (venue_name IS NULL OR trim(venue_name)='' OR description IS NULL OR trim(description)='') ORDER BY title"
    ).fetchall()
    lines.append("    none" if not rows else "    " + cap_list([r["title"] for r in rows]))
    lines.append("  events missing image_url:")
    rows = cur.execute(
        "SELECT id,title FROM events WHERE status='published' AND (image_url IS NULL OR trim(image_url)='') ORDER BY title"
    ).fetchall()
    lines.append("    none" if not rows else "    " + cap_list([r["title"] for r in rows]))

    return ok, "\n".join(lines)


# ---------------------------------------------------------------------------
# G2 — Cinema
# ---------------------------------------------------------------------------
def gate_cinema(cur) -> tuple[bool, str]:
    today = date.today().isoformat()
    total = cur.execute(
        "SELECT COUNT(*) FROM cinema_events WHERE status='published'"
    ).fetchone()[0]
    n_img = total - cur.execute(
        "SELECT COUNT(*) FROM cinema_events WHERE status='published' AND (image_url IS NULL OR trim(image_url)='')"
    ).fetchone()[0]
    n_desc = total - cur.execute(
        "SELECT COUNT(*) FROM cinema_events WHERE status='published' AND (description IS NULL OR trim(description)='')"
    ).fetchone()[0]
    stale = cur.execute(
        "SELECT title FROM cinema_events WHERE status='published' AND end_date IS NOT NULL AND end_date < ? ORDER BY end_date",
        (today,),
    ).fetchall()

    p_img = pct(n_img, total)
    p_desc = pct(n_desc, total)
    ok = p_img >= G2_IMAGE_PCT and p_desc >= G2_DESC_PCT and not stale

    lines = [
        f"  G2 published films: {total}",
        f"  image_url coverage: {p_img:.1f}% (target {G2_IMAGE_PCT:.0f}%)",
        f"  description coverage: {p_desc:.1f}% (target {G2_DESC_PCT:.0f}%)",
        f"  films missing poster (image_url):",
        "    " + (cap_list([r["title"] for r in cur.execute(
            "SELECT title FROM cinema_events WHERE status='published' AND (image_url IS NULL OR trim(image_url)='') ORDER BY title").fetchall()]) or "none"),
        f"  films missing description:",
        "    " + (cap_list([r["title"] for r in cur.execute(
            "SELECT title FROM cinema_events WHERE status='published' AND (description IS NULL OR trim(description)='') ORDER BY title").fetchall()]) or "none"),
        f"  STALE films (end_date < today={today}): {len(stale)}",
    ]
    stale_titles = [r["title"] for r in stale]
    lines.append("    " + (cap_list(stale_titles) if stale_titles else "none"))
    return ok, "\n".join(lines)


# ---------------------------------------------------------------------------
# G3 — Map mappability
# ---------------------------------------------------------------------------
def gate_map(cur) -> tuple[bool, str]:
    active = cur.execute(
        "SELECT COUNT(*) FROM events WHERE status='published'"
    ).fetchone()[0]
    resolved = cur.execute(
        "SELECT COUNT(*) FROM events e JOIN venues v ON e.venue_name = v.name "
        "WHERE e.status='published' AND e.venue_name IS NOT NULL AND trim(e.venue_name)!='' "
        "AND v.latitude IS NOT NULL AND v.longitude IS NOT NULL"
    ).fetchone()[0]
    mappable = pct(resolved, active)
    ok = mappable >= G3_MAP_PCT
    with_venue = cur.execute(
        "SELECT COUNT(*) FROM events WHERE status='published' "
        "AND venue_name IS NOT NULL AND trim(venue_name)!=''"
    ).fetchone()[0]
    lines = [
        f"  G3 active events: {active}",
        f"  events with venue_name: {with_venue}",
        f"  venue_name resolving to venue with lat/lng: {resolved}",
        f"  mappability: {mappable:.1f}% (target {G3_MAP_PCT:.0f}%)",
    ]
    return ok, "\n".join(lines)


def main() -> int:
    con = connect_ro()
    cur = con.cursor()
    exit_code = 0

    g1_ok, g1_txt = gate_content(cur)
    g2_ok, g2_txt = gate_cinema(cur)
    g3_ok, g3_txt = gate_map(cur)

    gates = [
        ("G1", g1_ok, g1_txt, 1),
        ("G2", g2_ok, g2_txt, 2),
        ("G3", g3_ok, g3_txt, 4),
    ]
    for name, ok, txt, bit in gates:
        status = "PASS" if ok else "FAIL"
        print(f"GATE {name}: {status}")
        print(txt)
        print()
        if not ok:
            exit_code |= bit

    print(f"OVERALL: {'ALL GATES PASS' if exit_code == 0 else 'ONE OR MORE GATES FAILED'} (exit={exit_code})")
    con.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
