#!/usr/bin/env python3
"""Build pipeline: merge events.json + cinema_events.json → index.html"""
import json, os, re, sys
from datetime import datetime, timezone

# T03: import atomic write helpers from the project package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scripts.models import write_atomic_json, write_atomic_text
from scripts.storage import get_storage  # T10: SQLite canonical source

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
INDEX_HTML = os.path.join(SCRIPT_DIR, "index.html")
INDEX_TEMPLATE = os.path.join(SCRIPT_DIR, "index.html.template")
# T27: review queue page (operator UI on top of /api/review/*).
REVIEW_HTML = os.path.join(SCRIPT_DIR, "review.html")
REVIEW_TEMPLATE = os.path.join(SCRIPT_DIR, "review.html.template")
# T28: about page (sources, methodology, threshold policy).
ABOUT_HTML = os.path.join(SCRIPT_DIR, "about.html")
ABOUT_TEMPLATE = os.path.join(SCRIPT_DIR, "about.html.template")
EVENTS_JSON = os.path.join(DATA_DIR, "events.json")
CINEMA_JSON = os.path.join(DATA_DIR, "cinema_events.json")
VENUES_JSON = os.path.join(DATA_DIR, "venues.json")
LASTRUN_JSON = os.path.join(DATA_DIR, "last_build.json")

# T19: build artefact history.
# Each successful build snapshots index.html into data/builds/ so operators
# can roll back without re-running the pipeline. Keeps last BUILDS_KEEP.
BUILDS_DIR = os.path.join(DATA_DIR, "builds")
BUILDS_KEEP = 30


def snapshot_build(
    html: str, events_count: int, cinema_count: int
) -> str:
    """T19: keep a versioned copy of each successful build.

    Writes:
      - data/builds/index.<built_at_safe>.html  (the snapshot)
      - data/builds/latest.json  (pointer + summary)

    Prunes oldest snapshots beyond BUILDS_KEEP (newest survives).
    Returns the snapshot filename (relative to BUILDS_DIR).
    """
    os.makedirs(BUILDS_DIR, exist_ok=True)

    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Filesystem-safe: collapse to ISO-basic. The Z suffix and the +00:00
    # offset both become dashes so no colons leak into the filename.
    safe = (
        built_at.replace("+00:00", "Z")
                .replace(":", "-")
    )
    fname = f"index.{safe}.html"
    fpath = os.path.join(BUILDS_DIR, fname)

    write_atomic_text(fpath, html)

    write_atomic_json(
        os.path.join(BUILDS_DIR, "latest.json"),
        {
            "latest": fname,
            "built_at": built_at,
            "events": events_count,
            "cinema": cinema_count,
            "size_bytes": len(html.encode("utf-8")),
        },
    )

    # Prune oldest beyond BUILDS_KEEP (keep newest by mtime).
    snapshots = sorted(
        (
            f
            for f in os.listdir(BUILDS_DIR)
            if f.startswith("index.") and f.endswith(".html")
        ),
        key=lambda f: os.path.getmtime(os.path.join(BUILDS_DIR, f)),
        reverse=True,
    )
    for old in snapshots[BUILDS_KEEP:]:
        try:
            os.unlink(os.path.join(BUILDS_DIR, old))
        except OSError:
            pass

    return fname


def load_events():
    # T10: read from SQLite (canonical). JSON files are now build artefacts
    # produced by this same script at the end of a build.
    storage = get_storage()
    events = storage.get_events(status=None)  # include everything; cinema filter below
    # Filter out cinema-category events — they're duplicates of cinema_events.json
    # and belong only in the dedicated cinema section
    events = [e for e in events if e.get("category", "").lower() != "cinema"]
    return events


def load_cinema():
    # T10: read from SQLite
    return get_storage().get_cinema()


VENUE_LOOKUP = {
    "Le Vox": "Le Vox", "Espace Animation": "Espace Animation", "Place du Mont": "Place du Mont-Blanc",
    "Eglise Saint": "Eglise Saint-Michel", "Presbytere": "Presbytere Saint-Michel",
    "Musee des": "Musee des Cristaux", "Observatoire": "Observatoire du Mont-Blanc",
    "Centre sportif": "Centre sportif Richard Bozon", "Tennis de": "Tennis de Chamonix",
    "Ferme du": "Ferme du Pain de Chibon", "Lac des Chavants": "Lac des Chavants",
    "Lac des Gaillands": "Lac des Gaillands", "Mairie Les Houches": "Mairie Les Houches",
    "Maison de Village": "Maison de Village d'Argentiere", "Pre de l": "Pre de l'Eglise",
    "Espace Michel": "Espace Michel Croz", "Maison des Artistes": "Maison des Artistes",
}

def resolve_venue(e):
    """Map an event to a known venue by venue field, address, or title."""
    v = e.get("venue", "") or e.get("venue_name", "") or ""
    venues_ref_data = load_venues()
    # Handle venues with or without "key" field — use "name" as fallback key
    venues_ref = {}
    for vd in venues_ref_data:
        k = vd.get("key") or vd.get("name", "")
        if k:
            venues_ref[k] = vd
    
    # Direct match
    if v and v in venues_ref:
        return v
    
    addr = (e.get("address") or "").lower()
    title = (e.get("title") or "").lower()
    text = v.lower() + " " + addr
    
    # Pattern matching from VENUE_LOOKUP
    for pattern, key in VENUE_LOOKUP.items():
        if pattern.lower() in text or pattern.lower() in addr or pattern.lower() in title:
            return key
    
    # Hardcoded event title matches
    if "film" in title and ("festival" in title or "fest" in title):
        return "Espace Michel Croz"
    if "market" in title:
        return "Place du Mont-Blanc"
    if "marathon" in title:
        return "Place du Mont-Blanc"
    if "mairie" in addr or "mairie" in title:
        if "houches" in addr:
            return "Mairie Les Houches"
        return "Mairie Les Houches"
    if "espace animation" in addr:
        return "Espace Animation"
    if "musee" in addr or "cristaux" in addr:
        return "Musee des Cristaux"
    if "eglise" in addr or "saint-michel" in addr or "presbytere" in addr:
        return "Eglise Saint-Michel"
    if "argentiere" in addr:
        return "Maison de Village d Argentiere"
    if "place du mont" in addr or "place du triangle" in addr:
        return "Place du Mont-Blanc"
    if "ferme" in addr and "pain" in addr:
        return "La ferme du Pain de Chibon"
    if "lac" in addr and "chavants" in addr:
        return "Lac des Chavants"
    if "lac" in addr and "gaillands" in addr:
        return "Lac des Gaillands"
    if "centre sportif" in addr:
        return "Centre sportif Richard Bozon"
    if "tennis" in addr:
        return "Tennis de Chamonix"
    if "observatoire" in addr:
        return "Observatoire du Mont-Blanc"
    if "espace michel" in addr or "emc" in addr:
        return "Espace Michel Croz"
    
    # If we have a recognizable venue name from the event, use it
    if v and not v.startswith("http"):
        return v
    
    return "Chamonix"

def load_venues():
    # T10: prefer SQLite venues table (populated by migration); fall back to JSON.
    venues = get_storage().get_venues()
    if not venues and os.path.exists(VENUES_JSON):
        with open(VENUES_JSON) as f:
            venues = json.load(f)
    if not venues:
        return []
    # T21: normalize lat/lng field names for downstream consumers.
    # SQLite stores latitude/longitude; the JS template (and any
    # consumer expecting lat/lng) needs the normalized form.
    # Without this, getVenueCoords() returns null for every venue
    # and the map shows no markers.
    out = []
    for v in venues:
        d = dict(v)  # shallow copy — don't mutate the storage rows
        if d.get("latitude") is not None and d.get("longitude") is not None:
            d["lat"] = d["latitude"]
            d["lng"] = d["longitude"]
        # T21: SQLite stores categories as a JSON-encoded string
        # (T18); parse it back into a Python list so downstream
        # consumers (JS template, JSON serialization) see a list.
        cats = d.get("categories")
        if isinstance(cats, str):
            try:
                d["categories"] = json.loads(cats)
            except json.JSONDecodeError:
                d["categories"] = []
        elif cats is None:
            d["categories"] = []
        out.append(d)
    return out


def build_venues(events):
    """Build venue list from authoritative data + event counts."""
    # Start with authoritative venues
    ref = load_venues()  # T21: load_venues normalizes lat/lng already
    if not ref:
        return []

    venue_map = {}
    for v in ref:
        k = v.get("key") or v.get("name", "")
        if k:
            venue_map[k] = v
    
    # Count events per venue
    for i, e in enumerate(events):
        vname = resolve_venue(e)
        if vname not in venue_map:
            # Add unknown venue
            venue_map[vname] = {
                "key": vname, "name": vname, "type": e.get("category","Venue").capitalize(),
                "location": e.get("commune","Chamonix"), "desc": "",
                "count": 0, "categories": set(), "indices": [], "lat": 0, "lng": 0,
                "image": ""
            }
        venue_map[vname]["count"] = venue_map[vname].get("count", 0) + 1
        venue_map[vname]["indices"] = venue_map[vname].get("indices", []) + [i]
        venue_map[vname]["categories"].add(e.get("category", ""))

    venues = []
    for vname in sorted(venue_map.keys()):
        v = venue_map[vname]
        v["categories"] = sorted(v["categories"])
        venues.append(v)

    return venues


def count_venues_with_coords(venues: list[dict]) -> int:
    """T21: how many venues have usable map coords.

    Used by main() to decide whether to render the map toggle button.
    The button is hidden if this returns 0 (per the plan: "hide map if
    no pins"). Counts venues with non-null, non-zero lat AND lng.
    """
    return sum(1 for v in venues if v.get("lat") and v.get("lng"))


def generate_html(events, venues, cinema=None, has_coorded_venues=True):
    """Read base template and inject EVENTS/VENUES/CINEMA_EVENTS data.

    T21: has_coorded_venues=False hides the map toggle button via inline
    style. Defaults True for backward compatibility with any callers
    that don't yet pass the flag.
    """
    # Try template first (has markers), fall back to index.html
    if os.path.exists(INDEX_TEMPLATE):
        with open(INDEX_TEMPLATE) as f:
            html = f.read()
    else:
        with open(INDEX_HTML) as f:
            html = f.read()

    # Inject EVENTS (marker replacement) — cinema excluded from main EVENTS
    events_json = json.dumps(events, ensure_ascii=False)
    if '<!-- EVENTS_DATA -->' in html:
        html = html.replace('<!-- EVENTS_DATA -->', 'var EVENTS = ' + events_json + ';')

    # Inject VENUES (marker replacement)
    venues_json = json.dumps(venues, ensure_ascii=False)
    if '<!-- VENUES_DATA -->' in html:
        html = html.replace('<!-- VENUES_DATA -->', 'var VENUES = ' + venues_json + ';')

    # Inject CINEMA_EVENTS (separate data for cinema section only)
    cinema_json = json.dumps(cinema or [], ensure_ascii=False)
    if '<!-- CINEMA_DATA -->' in html:
        html = html.replace('<!-- CINEMA_DATA -->', 'var CINEMA_EVENTS = ' + cinema_json + ';')

    # T21: hide map toggle if no venues have coords.
    # Marker is inside the button's class attribute; replace with
    # style="display:none" if no coorded venues, else empty.
    map_style = '' if has_coorded_venues else 'style="display:none"'
    if '<!-- MAP_TOGGLE_STYLE -->' in html:
        html = html.replace('<!-- MAP_TOGGLE_STYLE -->', map_style)

    # T22: TMDB attribution footer. We always emit the block when the key
    # is configured (even if no cinema events exist this week — attribution
    # is a per-page requirement, not a per-event one). When the key is
    # absent, the section is hidden via CSS (.tmdb-attr{display:none}).
    tmdb_html = ''
    try:
        from scripts import tmdb as _tmdb_mod
        if _tmdb_mod.get_api_key():
            tmdb_html = _tmdb_mod.ATTRIBUTION_HTML
    except ImportError:
        pass
    if '<!-- TMDB_ATTRIBUTION -->' in html:
        html = html.replace('<!-- TMDB_ATTRIBUTION -->', tmdb_html)

    # Update last built timestamp
    from datetime import datetime, timezone
    build_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    html = re.sub(
        r'<!-- build: .*? -->',
        f'<!-- build: {build_time} -->',
        html
    )

    return html


def sort_times(times):
    """Sort time strings like '11:00', '18:00' etc chronologically"""
    return sorted(times, key=lambda t: t.split(":"))



def render_review_page() -> bool:
    """T27: write review.html from review.html.template.

    The template is essentially static (no placeholders for v1 — the page
    fetches live data from /api/review/*). We copy with an atomic write so
    a partial file is never served.

    Returns True if review.html was written, False if the template is
    missing (build proceeds without failing — review queue is optional).
    """
    if not os.path.exists(REVIEW_TEMPLATE):
        print(f"  [t27] {REVIEW_TEMPLATE} not found — skipping review.html")
        return False
    try:
        with open(REVIEW_TEMPLATE, "r", encoding="utf-8") as f:
            html = f.read()
        # Atomic write so a crash mid-write can't truncate the served page.
        write_atomic_text(REVIEW_HTML, html)
        print(f"  [t27] wrote {REVIEW_HTML}")
        return True
    except OSError as exc:
        print(f"  [t27] failed to write review.html: {exc}", file=sys.stderr)
        return False


def render_about_page() -> bool:
    """T28: write about.html from about.html.template.

    Static content-only page (sources, methodology, threshold policy).
    Same atomic-write discipline as the other static pages.
    """
    if not os.path.exists(ABOUT_TEMPLATE):
        print(f"  [t28] {ABOUT_TEMPLATE} not found — skipping about.html")
        return False
    try:
        with open(ABOUT_TEMPLATE, "r", encoding="utf-8") as f:
            html = f.read()
        write_atomic_text(ABOUT_HTML, html)
        print(f"  [t28] wrote {ABOUT_HTML}")
        return True
    except OSError as exc:
        print(f"  [t28] failed to write about.html: {exc}", file=sys.stderr)
        return False


def main():
    events = load_events()
    print(f"Regular events: {len(events)}")

    cinema = load_cinema()
    print(f"Cinema events: {len(cinema)}")

    # Sort showtimes chronologically in each event
    for e in cinema:
        if e.get("showtimes"):
            for day in e["showtimes"]:
                e["showtimes"][day] = sort_times(e["showtimes"][day])
            # Remove duplicate times (but keep if they're different languages — need to handle this)
            # For now, deduplicate exact same time strings
            for day in e["showtimes"]:
                seen = set()
                unique = []
                for t in e["showtimes"][day]:
                    if t not in seen:
                        seen.add(t)
                        unique.append(t)
                e["showtimes"][day] = unique

    # Cinema expiry: remove films whose screening dates have passed
    from datetime import datetime as dt2
    today_str = dt2.now().isoformat()[:10]
    cinema = [c for c in cinema if not c.get('end_date') or c['end_date'] >= today_str]

    # IMPORTANT: cinema is NOT merged into events for the main rolling calendar.
    # Cinema only appears in the dedicated cinema section (CINEMA_EVENTS).
    # But venues still include cinema venues — use all_events for venue building.
    # T11: unified cross-source dedup via storage layer (replaces local
    # build-time dedup that conflicted with per-scraper dedup).
    # load_events() already filtered out cinema-category events.
    merged = get_storage().dedupe_events(events)
    all_events = merged + cinema
    print(f"Regular events (after dedup): {len(merged)}")
    print(f"Cinema events (separate): {len(cinema)}")
    print(f"All events (for venues): {len(all_events)}")

    # Build venues from all events (including cinema for venue counts)
    venues_data = load_venues()
    if not venues_data:
        venues_data = build_venues(all_events)

    # Add cinema venues if not present
    cinema_venues = {}
    for e in cinema:
        vn = e.get("venue", "Le Vox")
        if vn not in cinema_venues:
            cinema_venues[vn] = {
                "name": vn, "key": vn, "type": "Cinema", "location": "Centre-ville",
                "desc": "Cinema emblematique", "count": 0, "categories": ["Cinema"],
                "indices": [], "lat": 45.9214, "lng": 6.8697, "image": ""
            }
        cinema_venues[vn]["count"] = cinema_venues[vn].get("count", 0) + 1

    # Add any cinema venues not already in the list
    existing_keys = set()
    for v in venues_data:
        k = v.get("key") or v.get("name", "")
        if k:
            existing_keys.add(k)
    for cv_key, cv in cinema_venues.items():
        if cv_key not in existing_keys:
            # Find index in all_events
            cv["indices"] = [i for i, e in enumerate(all_events) if e.get("venue") == cv_key]
            venues_data.append(cv)
        else:
            # Update existing venue
            for v in venues_data:
                vk = v.get("key") or v.get("name", "")
                if vk == cv_key:
                    v["count"] = cv["count"]
                    v["indices"] = [i for i, e in enumerate(all_events) if e.get("venue") == cv_key]
                    v["categories"] = ["Cinema"]
                    break

    # Count events per venue from resolved venue names (all events for accurate counts)
    event_venue_counts = {}
    for i, e in enumerate(all_events):
        vname = resolve_venue(e)
        if vname:
            event_venue_counts[vname] = event_venue_counts.get(vname, 0) + 1

    # Update venue counts and indices from real event data
    for v in venues_data:
        key = v.get("key") or v.get("name", "")
        if not key:
            continue
        v["count"] = event_venue_counts.get(key, 0)
        v["indices"] = [i for i, e in enumerate(all_events) if resolve_venue(e) == key]
        # T21: only override curated categories if at least one event
        # matches this venue. Otherwise keep the curated categories
        # from venues.json (T18). Without this guard, every venue
        # gets its categories overwritten with [] because events
        # don't currently link to venues (audit gap).
        matched_cats = sorted(set(
            e.get("category", "other") for e in all_events if resolve_venue(e) == key
        ))
        if matched_cats:
            v["categories"] = matched_cats

    # Write venues — REMOVED: venues.json is a git-controlled reference file.
    # Computed venue counts go into the HTML only.
    # This avoids overwriting the 26-venue reference file on every build.

    # Generate HTML — pass cinema separately for dedicated section
    # T21: pass has_coorded_venues so the map toggle hides when no
    # venues have usable coords (per the plan: "hide map if no pins").
    has_coorded = count_venues_with_coords(venues_data) > 0
    html = generate_html(merged, venues_data, cinema, has_coorded_venues=has_coorded)

    # Write HTML (always use index.html, don't recreate backup)
    # Template file is the canonical source
    # T03: atomic write so a crash mid-write doesn't truncate the served page.
    write_atomic_text(INDEX_HTML, html)

    # T27: review queue operator UI (separate page, same atomic-write
    # discipline). No data placeholders — page fetches /api/review/* at runtime.
    render_review_page()

    # T28: about page (sources, methodology, threshold policy).
    # Static content-only, no placeholders.
    render_about_page()

    # T19: keep a versioned copy so operators can roll back without
    # re-running the pipeline. Pruned to BUILDS_KEEP by snapshot_build.
    snapshot_name = snapshot_build(html, len(merged), len(cinema))
    print(f"Build snapshot: data/builds/{snapshot_name}")

    # T10: write JSON build artefacts so nginx keeps serving the same URLs.
    # These are now derived from SQLite.
    write_atomic_json(EVENTS_JSON, merged)
    write_atomic_json(CINEMA_JSON, cinema)

    print(f"Written {INDEX_HTML}")
    print(f"Events: {len(merged)}, Venues: {len(venues_data)}")

    # T10: also persist build metadata to SQLite (single source of truth)
    # in addition to last_build.json (for /healthz compatibility).
    get_storage().write_build_metadata(events_count=len(merged), cinema_count=len(cinema))
    # T03: atomic write for last_build.json (timestamp + counts feed /healthz)
    write_atomic_json(
        LASTRUN_JSON,
        {"built_at": datetime.now(timezone.utc).isoformat(), "events": len(merged), "cinema": len(cinema)},
    )


if __name__ == "__main__":
    main()
