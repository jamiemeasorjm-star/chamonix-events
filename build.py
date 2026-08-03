#!/usr/bin/env python3
"""Build pipeline: merge events.json + cinema_events.json → index.html + event detail pages + sitemap"""
import html
import json, os, re, sys
import unicodedata
from datetime import datetime, timezone

# T03: import atomic write helpers from the project package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scripts.models import write_atomic_json, write_atomic_text
from scripts.storage import get_storage  # T10: SQLite canonical source

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
EVENTS_DIR = os.path.join(SCRIPT_DIR, "events")  # T41: individual event pages
INDEX_HTML = os.path.join(SCRIPT_DIR, "index.html")
INDEX_TEMPLATE = os.path.join(SCRIPT_DIR, "index.html.template")
# T27: review queue page (operator UI on top of /api/review/*).
REVIEW_HTML = os.path.join(SCRIPT_DIR, "review.html")
REVIEW_TEMPLATE = os.path.join(SCRIPT_DIR, "review.html.template")
# T28: about page (sources, methodology, threshold policy).
ABOUT_HTML = os.path.join(SCRIPT_DIR, "about.html")
ABOUT_TEMPLATE = os.path.join(SCRIPT_DIR, "about.html.template")
# T32: manual event submission page.
SUBMIT_HTML = os.path.join(SCRIPT_DIR, "submit.html")
SUBMIT_TEMPLATE = os.path.join(SCRIPT_DIR, "submit.html.template")
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
    events = storage.get_events(status="published")  # only published events
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

    # T24: apply per-language field fallbacks before JSON emission
    from scripts.storage import localized
    events = [localized(e) for e in events]
    venues = [localized(v) for v in venues]
    if cinema:
        cinema = [localized(c) for c in cinema]

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

    # Update last built timestamp (T-fix H1): stamp a <meta> tag instead of
    # re.sub'ing an HTML comment. The old regex `<!-- build: .*? -->` ALSO
    # matched the JS regex literal inside showBuildTime(), destroying its
    # capture group and rendering the footer's build-age as "NaNj". Reading a
    # meta tag avoids the collision entirely.
    from datetime import datetime, timezone
    build_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    html = re.sub(
        r'<meta name="build-time" content="([^"]*)"',
        f'<meta name="build-time" content="{build_time}"',
        html,
        count=1,
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


def _render_static(name: str, label: str, template_name: str, output_name: str) -> bool:
    """Generic static page renderer — copies template to output with atomic write.

    Used for pages that have no data placeholders (privacy, terms, etc.).
    """
    template_path = os.path.join(SCRIPT_DIR, template_name)
    output_path = os.path.join(SCRIPT_DIR, output_name)
    if not os.path.exists(template_path):
        print(f"  [{name}] {template_path} not found — skipping {output_name}")
        return False
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()
        write_atomic_text(output_path, html)
        print(f"  [{name}] wrote {output_name}")
        return True
    except OSError as exc:
        print(f"  [{name}] failed to write {output_name}: {exc}", file=sys.stderr)
        return False


def render_submit_page() -> bool:
    """T32: write submit.html from submit.html.template.

    Static content-only page (manual event submission form).
    Same atomic-write discipline as the other static pages.
    """
    if not os.path.exists(SUBMIT_TEMPLATE):
        print(f"  [t32] {SUBMIT_TEMPLATE} not found — skipping submit.html")
        return False
    try:
        with open(SUBMIT_TEMPLATE, "r", encoding="utf-8") as f:
            html = f.read()
        write_atomic_text(SUBMIT_HTML, html)
        print(f"  [t32] wrote {SUBMIT_HTML}")
        return True
    except OSError as exc:
        print(f"  [t32] failed to write submit.html: {exc}", file=sys.stderr)
        return False


# ----- T41: individual event pages, sitemap, robots --------------------------

EVENT_TEMPLATE = os.path.join(SCRIPT_DIR, "event.html.template")
SITEMAP_XML = os.path.join(SCRIPT_DIR, "sitemap.xml")
ROBOTS_TXT = os.path.join(SCRIPT_DIR, "robots.txt")
SITE_URL = "https://events.chamonix.app"  # base for canonical/OG URLs


def slugify(text: str, date_suffix: str | None = None) -> str:
    """Convert text to a URL-safe slug (lowercase ASCII, hyphens only).

    Handles French accented chars (é→e, è→e, ç→c, etc.) and strips
    non-alphanumeric characters. Used for event detail page filenames.

    When date_suffix is provided (e.g. "2026-07-24"), a short date
    hash is appended to disambiguate events with identical titles.
    """
    text = text.lower().strip()
    # Normalize unicode (NFD decomposes é → e + combining accent)
    text = unicodedata.normalize("NFD", text)
    # Strip combining diacritical marks
    text = re.sub(r"[\u0300-\u036f]", "", text)
    # Replace non-alphanumeric with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text)
    # Strip leading/trailing hyphens
    text = text.strip("-")
    # Collapse multiple hyphens
    text = re.sub(r"-+", "-", text)
    # Remove trailing date pattern if present (e.g. "-2026-07-24")
    text = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", text)
    # Append date suffix for uniqueness when provided
    if date_suffix and len(date_suffix) >= 7:
        short_date = date_suffix[:7].replace("-", "")  # e.g. "202607"
        text = f"{text[:60]}-{short_date}"
    return text[:80] or "event"


def _meta_desc(desc: str, maxlen: int = 200) -> str:
    """First meaningful sentence or truncated text for meta description."""
    desc = (desc or "").strip()
    if not desc:
        return "Event in Chamonix, France"
    # Try first sentence
    sentences = re.split(r"[.!?\n]+", desc)
    for s in sentences:
        s = s.strip()
        if len(s) > 20:
            if len(s) <= maxlen:
                return html.escape(s)
            return html.escape(s[:maxlen].rsplit(" ", 1)[0] + "…")
    return html.escape(desc[:maxlen])


def _format_date_range(start: str, end: str | None) -> str:
    """Human-readable date range like 'Jul 2 → Sep 30, 2026'."""
    from datetime import datetime as dt
    fmt = "%b %d, %Y"
    s = dt.fromisoformat(start).strftime(fmt) if start else ""
    e = dt.fromisoformat(end).strftime(fmt) if end else ""
    if s and e and start != end:
        return f"{s} → {e}"
    return s or e or ""


def generate_event_pages(events: list[dict]) -> int:
    """T41: generate /events/<slug>.html for each published event.

    Reads event.html.template, fills in per-event placeholders, writes
    atomically. Returns count of pages written.

    Each page includes:
      - Full event title, date, time, venue, commune, price, website
      - OG / Twitter Card meta tags for social sharing
      - Schema.org/Event JSON-LD structured data
      - "Add to Calendar" (iCal) link (will work once T42 is done)
      - Back-to-events navigation
    """
    if not os.path.exists(EVENT_TEMPLATE):
        print(f"  [t41] {EVENT_TEMPLATE} not found — skipping event pages")
        return 0

    with open(EVENT_TEMPLATE, "r", encoding="utf-8") as f:
        tmpl = f.read()

    os.makedirs(EVENTS_DIR, exist_ok=True)
    count = 0

    written_slugs: set[str] = set()
    for e in events:
        # Use event id as base for deterministic slug (already unique)
        date_part = e.get("start_date") or e.get("end_date") or ""
        slug = slugify(e.get("id", e.get("title", "event")), date_suffix=date_part)
        # Fallback: if slug still collides, add a numeric suffix
        if slug in written_slugs:
            n = 2
            while f"{slug}-{n}" in written_slugs:
                n += 1
            slug = f"{slug}-{n}"
        written_slugs.add(slug)

        title = e.get("title", "Event")
        title_en = e.get("title_en") or e.get("title") or ""
        desc_html = (e.get("description") or "").replace("\n", "<br>")
        desc_plain = _meta_desc(e.get("description", ""))
        category = e.get("category", "other").capitalize()
        date_str = _format_date_range(e.get("start_date", ""), e.get("end_date"))
        time_str = e.get("time") or "All day"
        venue_name = e.get("venue_name") or e.get("venue") or "Chamonix"
        commune = e.get("commune", "Chamonix")
        price = e.get("price")
        website = e.get("website") or e.get("source_url", "")
        source_url = e.get("source_url", "")

        # OG / Twitter Card tags
        og_title = html.escape(title)
        og_desc = html.escape(desc_plain)
        og_url = f"{SITE_URL}/events/{slug}.html"
        og_tags = (
            f'<meta property="og:type" content="website">\n'
            f'<meta property="og:url" content="{og_url}">\n'
            f'<meta property="og:title" content="{og_title} — Chamonix Events">\n'
            f'<meta property="og:description" content="{og_desc}">\n'
            f'<meta property="og:site_name" content="Chamonix Events">'
        )
        twitter_tags = (
            f'<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:title" content="{og_title} — Chamonix Events">\n'
            f'<meta name="twitter:description" content="{og_desc}">'
        )
        if e.get("image_url") and not e["image_url"].startswith("data:"):
            og_tags += f'\n<meta property="og:image" content="{html.escape(e["image_url"])}">'
            twitter_tags += f'\n<meta name="twitter:image" content="{html.escape(e["image_url"])}">'

        # Schema.org JSON-LD
        json_ld = {
            "@context": "https://schema.org",
            "@type": "Event",
            "name": title,
            "description": e.get("description", ""),
            "startDate": e.get("start_date", ""),
            "url": og_url,
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "eventStatus": "https://schema.org/EventScheduled",
            "location": {
                "@type": "Place",
                "name": venue_name,
                "address": {"@type": "PostalAddress", "addressLocality": commune},
            },
        }
        if e.get("end_date") and e["end_date"] != e.get("start_date"):
            json_ld["endDate"] = e["end_date"]
        if e.get("image_url") and not e["image_url"].startswith("data:"):
            json_ld["image"] = e["image_url"]
        json_ld_str = json.dumps(json_ld, ensure_ascii=False).replace("</script>", "<\\/script>")

        # Price meta
        price_block = ""
        if price:
            price_block = (
                f'<div class="meta-item"><div class="meta-label">Price</div>'
                f'<div class="meta-value">{html.escape(str(price))}</div></div>'
            )
        website_block = ""
        if website:
            website_block = (
                f'<div class="meta-item"><div class="meta-label">Website</div>'
                f'<div class="meta-value"><a class="venue-link" href="{html.escape(website)}" '
                f'target="_blank" rel="noopener">{html.escape(website[:40])}…</a></div></div>'
            )

        # Bilingual title subtitle
        title_en_html = ""
        if title_en and title_en != title:
            title_en_html = (
                f'<p style="font-size:.85rem;color:var(--text3);font-family:var(--ff-sans);'
                f'font-weight:400;margin-top:4px">{html.escape(title_en)}</p>'
            )

        page = tmpl
        page = page.replace("__EVENT_TITLE__", html.escape(title))
        page = page.replace("__EVENT_TITLE_EN__", title_en_html)
        page = page.replace("__EVENT_DESC_PLAIN__", desc_plain)
        page = page.replace("__EVENT_CATEGORY__", category)
        page = page.replace("__EVENT_DATE__", html.escape(date_str))
        page = page.replace("__EVENT_TIME__", html.escape(time_str))
        page = page.replace("__EVENT_VENUE__", html.escape(venue_name))
        page = page.replace("__EVENT_COMMUNE__", html.escape(commune))
        page = page.replace("__EVENT_DESCRIPTION__", desc_html)
        page = page.replace("__EVENT_SOURCE_URL__", html.escape(source_url))
        page = page.replace("__EVENT_PRICE__", price_block)
        page = page.replace("__EVENT_WEBSITE__", website_block)
        page = page.replace("__OG_TAGS__", og_tags)
        page = page.replace("__TWITTER_TAGS__", twitter_tags)
        page = page.replace("__JSON_LD__", f'<script type="application/ld+json">{json_ld_str}</script>')
        # iCal link (placeholder — works once T42 adds the endpoint)
        page = page.replace("__ICAL_LINK__", f'/api/events.ics?event={slug}')

        fpath = os.path.join(EVENTS_DIR, f"{slug}.html")
        write_atomic_text(fpath, page)
        count += 1

    print(f"  [t41] wrote {count} event pages to events/")
    return count


def generate_sitemap(events: list[dict], cinema: list[dict]) -> None:
    """T41: generate sitemap.xml listing all published event detail pages + static pages.

    Produces a valid sitemap with lastmod dates and change frequencies.
    Static pages (index, about, submit, review) are included at weekly cadence.
    Event pages use monthly cadence.
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    urls = []
    # Static pages
    for static_url, prio in [("", "1.0"), ("/about.html", "0.7"), ("/submit.html", "0.5"), ("/review.html", "0.3"), ("/privacy.html", "0.3")]:
        urls.append(f"""  <url>
    <loc>{SITE_URL}{static_url}</loc>
    <lastmod>{now_iso}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>{prio}</priority>
  </url>""")

    # Event pages
    seen_slugs: set[str] = set()
    for e in events:
        date_part = e.get("start_date") or e.get("end_date") or ""
        slug = slugify(e.get("id", e.get("title", "event")), date_suffix=date_part)
        if slug in seen_slugs:
            n = 2
            while f"{slug}-{n}" in seen_slugs:
                n += 1
            slug = f"{slug}-{n}"
        seen_slugs.add(slug)
        lastmod = (e.get("updated_at") or e.get("created_at") or now_iso)[:10]
        urls.append(f"""  <url>
    <loc>{SITE_URL}/events/{slug}.html</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""
    write_atomic_text(SITEMAP_XML, xml)
    print(f"  [t41] wrote sitemap.xml ({len(seen_slugs)} event URLs)")


def generate_robots() -> None:
    """T41: generate robots.txt allowing all crawlers, pointing to sitemap."""
    robots = f"""User-agent: *
Allow: /

Sitemap: {SITE_URL}/sitemap.xml
"""
    write_atomic_text(ROBOTS_TXT, robots)
    print("  [t41] wrote robots.txt")


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

    # T41: inject _slug field so JS can link to event detail pages
    # Uses same slug logic as generate_event_pages for consistency
    used_slugs: dict[str, int] = {}
    for e in merged:
        date_part = e.get("start_date") or e.get("end_date") or ""
        slug = slugify(e.get("id", e.get("title", "event")), date_suffix=date_part)
        if slug in used_slugs:
            used_slugs[slug] += 1
            slug = f"{slug}-{used_slugs[slug]}"
        else:
            used_slugs[slug] = 1
        e["_slug"] = slug
    for e in cinema:
        date_part = e.get("start_date") or e.get("end_date") or ""
        slug = slugify(e.get("id", e.get("title", "event")), date_suffix=date_part)
        if slug in used_slugs:
            used_slugs[slug] += 1
            slug = f"{slug}-{used_slugs[slug]}"
        else:
            used_slugs[slug] = 1
        e["_slug"] = slug

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

    # T32: manual event submission page.
    render_submit_page()

    # T46: privacy policy page.
    _render_static("privacy", "Privacy Policy", "privacy.html.template", "privacy.html")

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

    # T41: generate individual event pages (regular + cinema), sitemap, and robots.txt
    generate_event_pages(merged + cinema)
    generate_sitemap(merged, cinema)
    generate_robots()


if __name__ == "__main__":
    main()
