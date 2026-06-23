#!/usr/bin/env python3
"""Build pipeline: merge events.json + cinema_events.json → index.html"""
import json, os, re, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
INDEX_HTML = os.path.join(SCRIPT_DIR, "index.html")
INDEX_TEMPLATE = os.path.join(SCRIPT_DIR, "index.html.template")
EVENTS_JSON = os.path.join(DATA_DIR, "events.json")
CINEMA_JSON = os.path.join(DATA_DIR, "cinema_events.json")
VENUES_JSON = os.path.join(DATA_DIR, "venues.json")
LASTRUN_JSON = os.path.join(DATA_DIR, "last_build.json")


def load_events():
    events = []
    if os.path.exists(EVENTS_JSON):
        with open(EVENTS_JSON) as f:
            events = json.load(f)
    # Remove old cinema events (keep regular events)
    # PRESERVED cinema: events = [e for e in events if e.get("category") != "Cinema"]
    return events


def load_cinema():
    if os.path.exists(CINEMA_JSON):
        with open(CINEMA_JSON) as f:
            return json.load(f)
    return []


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
    if os.path.exists(VENUES_JSON):
        with open(VENUES_JSON) as f:
            return json.load(f)
    return []


def build_venues(events):
    """Build venue list from authoritative data + event counts."""
    # Start with authoritative venues
    ref = load_venues()
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


def generate_html(events, venues):
    """Read base template and inject EVENTS/VENUES data."""
    # Try template first (has markers), fall back to index.html
    if os.path.exists(INDEX_TEMPLATE):
        with open(INDEX_TEMPLATE) as f:
            html = f.read()
    else:
        with open(INDEX_HTML) as f:
            html = f.read()

    # Inject EVENTS (marker replacement)
    events_json = json.dumps(events, ensure_ascii=False)
    if '<!-- EVENTS_DATA -->' in html:
        html = html.replace('<!-- EVENTS_DATA -->', 'var EVENTS = ' + events_json + ';')

    # Inject VENUES (marker replacement)
    venues_json = json.dumps(venues, ensure_ascii=False)
    if '<!-- VENUES_DATA -->' in html:
        html = html.replace('<!-- VENUES_DATA -->', 'var VENUES = ' + venues_json + ';')

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



def deduplicate_events(events: list) -> list:
    """Remove cross-source duplicates by normalized title.
    Uses NFKD to normalize accented chars (E vs E), removes punctuation."""
    import unicodedata
    seen: dict[str, dict] = {}
    for e in events:
        title = (e.get("title") or "").strip().lower()
        # NFKD: E + circumflex and E + diaeresis both become e + combining mark
        title = unicodedata.normalize("NFKD", title)
        # Remove combining diacritical marks (accents)
        title = re.sub(r"[̀-ͯ]", "", title)
        # Remove age-rating prefix like "Int.—12 ans"
        title = re.sub(r"^int[.°]?\s*—\s*\d+\s+ans\s+", "", title, flags=re.IGNORECASE)
        # Remove all punctuation: dashes, quotes, colons, slashes
        title = re.sub("[\u2014\u2013\u2019\u2018\x22\x27\x3a\x5c/]+", "", title)
        title = re.sub(r"\s+", " ", title).strip()
        # Dedup by title only (dates differ across sources)
        if title in seen:
            existing = seen[title]
            new_score = sum(1 for f in ["description","image_url","time","venue"] if e.get(f))
            old_score = sum(1 for f in ["description","image_url","time","venue"] if existing.get(f))
            # Merge duration and language from losing event (e.g. PDF has duration, AlloCiné has poster)
            if new_score > old_score:
                # Copy duration/language from existing if missing in e
                for merge_field in ["duration", "language", "voice_versions"]:
                    if not e.get(merge_field) and existing.get(merge_field):
                        e[merge_field] = existing[merge_field]
            else:
                for merge_field in ["duration", "language", "voice_versions"]:
                    if not existing.get(merge_field) and e.get(merge_field):
                        existing[merge_field] = e[merge_field]
            if new_score > old_score:
                seen[title] = e
        else:
            seen[title] = e
    return list(seen.values())
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
    merged = deduplicate_events(events + cinema)
    print(f"Merged events: {len(merged)}")

    # Build venues from merged events
    venues_data = load_venues()
    if not venues_data:
        venues_data = build_venues(merged)

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
            # Find index in merged events
            cv["indices"] = [i for i, e in enumerate(merged) if e.get("venue") == cv_key]
            venues_data.append(cv)
        else:
            # Update existing venue
            for v in venues_data:
                vk = v.get("key") or v.get("name", "")
                if vk == cv_key:
                    v["count"] = cv["count"]
                    v["indices"] = [i for i, e in enumerate(merged) if e.get("venue") == cv_key]
                    v["categories"] = ["Cinema"]
                    break

    # Count events per venue from resolved venue names
    event_venue_counts = {}
    for i, e in enumerate(merged):
        vname = resolve_venue(e)
        if vname:
            event_venue_counts[vname] = event_venue_counts.get(vname, 0) + 1

    # Update venue counts and indices from real event data
    for v in venues_data:
        key = v.get("key") or v.get("name", "")
        if not key:
            continue
        v["count"] = event_venue_counts.get(key, 0)
        v["indices"] = [i for i, e in enumerate(merged) if resolve_venue(e) == key]
        v["categories"] = sorted(set(
            e.get("category", "other") for i, e in enumerate(merged) if resolve_venue(e) == key
        ))

    # Write venues
    with open(VENUES_JSON, "w") as f:
        json.dump(venues_data, f, indent=2, ensure_ascii=False)

    # Generate HTML
    html = generate_html(merged, venues_data)

    # Write HTML (always use index.html, don't recreate backup)
    # Template file is the canonical source

    with open(INDEX_HTML, "w") as f:
        f.write(html)

    print(f"Written {INDEX_HTML}")
    print(f"Events: {len(merged)}, Venues: {len(venues_data)}")

    # Write lastrun
    from datetime import datetime, timezone
    with open(LASTRUN_JSON, "w") as f:
        json.dump({"built_at": datetime.now(timezone.utc).isoformat(), "events": len(merged), "cinema": len(cinema)}, f)


if __name__ == "__main__":
    main()
