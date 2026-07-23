from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
SOURCE_ID = "chamonix_nightlife"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RECURRING_PATH = DATA_DIR / "nightlife_recurring.json"

VENUES = [
    ("Big Mountain Basecamp", "Chamonix", "https://www.bigmtnbrew.co/chamonix-basecamp/", "+33 4 50 53 40 75", "365 Avenue Ravanel le Rouge"),
    ("Big Mountain Festival", "Chamonix", "https://www.bigmtnbrew.co/festival/", "", ""),
    ("Le Solerey Brewpub", "Chamonix", "https://lesolereybrewpub.com/", "+33 4 56 37 46 85", "81 Avenue des Alpages"),
    ("The Beckett & Wilde", "Chamonix", "https://www.thebeckettandwilde.com/", "", ""),
    ("The Beckett & Wilde Live Music", "Chamonix", "https://www.thebeckettandwilde.com/livemusic", "", ""),
    ("The Beckett & Wilde Live Sports", "Chamonix", "https://www.thebeckettandwilde.com/livesports", "", ""),
    ("L'Alibi", "Chamonix", "", "", "Place de l'Eglise"),
    ("Le Chamonix", "Chamonix", "", "", "Place du Triangle de l'Amitie"),
    ("Bar du Moulin", "Chamonix", "", "", "Rue des Moulins"),
    ("Mix Bar", "Chamonix", "", "", "Rue des Moulins"),
    ("Le Shack!", "Chamonix", "", "", "Rue Whymper"),
    ("Maison des Artistes", "Chamonix", "", "", "Chemin de la Tournette"),
    ("Bar d'Up", "Chamonix", "", "", "Rue des Moulins"),
    ("Moo", "Chamonix", "", "", "Avenue Michel Croz"),
    ("French Blvd", "Chamonix", "", "", "Avenue du Mont-Blanc"),
    ("Stories", "Chamonix", "", "", "Avenue Ravanel le Rouge"),
    ("Couleur Cafe", "Chamonix", "", "", ""),
    ("Beer O'Clock", "Chamonix", "", "", "74 Avenue Ravanel le Rouge"),
    ("Synge&Co", "Chamonix", "", "", "Place Edmond Desailloud"),
    ("ChaChaCha", "Chamonix", "", "", "Avenue Ravanel le Rouge"),
    ("Moon Tines", "Chamonix", "", "", ""),
    ("O'Byrne's Pub", "Chamonix", "", "", ""),
    ("The Wine Factory", "Les Houches", "", "", ""),
    ("Cafe de la Gare", "Les Houches", "", "", ""),
    ("Les Copains d'Abord", "Les Houches", "", "", ""),
    ("Amnesia", "Chamonix", "", "", ""),
    ("Le Garage", "Chamonix", "", "", ""),
    ("South Bar", "Chamonix", "", "+33 6 89 17 80 33", ""),
]

FULL_MONTH_EN = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
FULL_MONTH_FR = r"(?:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)"
SHORT_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
DATE_PATTERNS = [
    rf"(\d{{1,2}})\s+({FULL_MONTH_EN})\s+(\d{{4}})",
    rf"(\d{{1,2}})\s+({FULL_MONTH_FR})\s+(\d{{4}})",
    rf"(\d{{1,2}})\s+({SHORT_MONTH})\w*\s+(\d{{4}})",
    r"(\d{1,2})/(\d{1,2})/(\d{4})",
    r"(\d{4})-(\d{2})-(\d{2})",
]

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _normalise_date(day_str: str, month_str: str, year_str: str) -> str | None:
    """Convert a parsed (day, month, year) into ISO date string, or None if invalid/past."""
    try:
        day = int(day_str)
        year = int(year_str)
        month = MONTH_MAP.get(month_str.lower() if month_str.isalpha() else month_str, 0)
        if not month:
            # numeric slash/iso: month_str is already a number
            try:
                month = int(month_str)
            except ValueError:
                return None
        iso = f"{year:04d}-{month:02d}-{day:02d}"
        # Reject past dates (older than yesterday) and bogus years
        if year < 2025 or year > 2030:
            return None
        # Reject dates more than 7 days in the past (allow some grace)
        today = date.today()
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            return None
        if d < today - timedelta(days=7):
            return None
        # Cap 18 months ahead
        if d > today + timedelta(days=540):
            return None
        return iso
    except Exception:
        return None


def _find_dates_in_text(text: str, min_count: int = 1) -> list[str]:
    """Find all parseable ISO dates in text, sorted, deduped."""
    out: list[str] = []
    for pat in DATE_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            g = m.groups()
            # Pattern order: text-day-name-year, text-day-name-year (FR), text-day-name-year (short),
            # slash-day-num-year, iso-year-num-num
            if len(g) == 3 and g[0].isdigit() and len(g[0]) == 4:
                # ISO format YYYY-MM-DD
                iso = _normalise_date(g[2], g[1], g[0])
            else:
                # All other patterns: (day, month, year) where month may be name or number
                iso = _normalise_date(g[0], g[1], g[2])
            if iso and iso not in out:
                out.append(iso)
    return out


def _extract_titles_around_dates(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Extract (date_iso, title) pairs from element-level scanning.

    For each leaf-ish element with a date, return the date plus the surrounding
    heading/text as a candidate title. Used to find specific event entries
    rather than just page-level dates.
    """
    candidates: list[tuple[str, str]] = []
    for el in soup.select("h1, h2, h3, h4, h5, p, li, article, section, div.event, .event-item, .calendar-item, .schedule-item"):
        txt = el.get_text(" ", strip=True)
        if not txt or len(txt) > 800:
            continue
        dates = _find_dates_in_text(txt)
        for d in dates:
            # Pull the first heading-like text as the title
            heading = el.find(["h1", "h2", "h3", "h4", "h5", "strong"])
            title = heading.get_text(" ", strip=True)[:120] if heading else txt[:120]
            if title and len(title) > 3:
                candidates.append((d, title))
    return candidates


def scrape_venue_events(url: str, venue_name: str, client: httpx.Client) -> list[dict]:
    """Scrape a venue's homepage + follow event/agenda links for dated entries."""
    events: list[dict] = []
    seen_links: set[str] = set()
    pages_to_visit: list[str] = [url]

    # Find candidate event/agenda subpages from homepage
    try:
        resp = client.get(url, follow_redirects=True, timeout=15.0)
        resp.raise_for_status()
        soup_home = BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return events

    # Direct candidates from homepage text
    for d, title in _extract_titles_around_dates(soup_home):
        events.append({
            "title": title,
            "start_date": d,
            "venue_name": venue_name,
            "source_url": url,
        })

    # Find followable event/agenda links
    event_keywords = ("event", "agenda", "calendar", "concert", "live", "music",
                      "whats-on", "what-s-on", "programme", "program", "festival",
                      "spectacle", "soiree", "soirée")
    for a in soup_home.select("a[href]"):
        href = a.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        absolute = urljoin(url, href)
        if absolute in seen_links or absolute == url:
            continue
        href_l = href.lower()
        if any(k in href_l for k in event_keywords):
            seen_links.add(absolute)
            pages_to_visit.append(absolute)

    # Cap at 6 subpages per venue to avoid runaway scraping
    pages_to_visit = pages_to_visit[:6]

    for page_url in pages_to_visit[1:]:
        try:
            resp = client.get(page_url, follow_redirects=True, timeout=15.0)
            resp.raise_for_status()
        except Exception:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for d, title in _extract_titles_around_dates(soup):
            events.append({
                "title": title,
                "start_date": d,
                "venue_name": venue_name,
                "source_url": page_url,
            })

    return events


def _schedule_to_dates(schedule: str, start_iso: str | None, end_iso: str | None,
                       horizon_days: int = 14) -> list[str]:
    """Expand a recurring schedule into concrete ISO dates within horizon.

    Returns dates from today to today+horizon_days. If start_iso is in the
    future and within horizon, use that instead. If end_iso is set, clamp.
    """
    today = date.today()
    horizon_end = today + timedelta(days=horizon_days)

    # Single specific date (annual / one-off)
    if schedule == "annual" or (start_iso and end_iso and start_iso == end_iso):
        if start_iso:
            try:
                d = date.fromisoformat(start_iso)
                if today <= d <= horizon_end:
                    return [start_iso]
            except ValueError:
                pass
        return []

    # Specific date range (e.g., festival week)
    if schedule == "seasonal" and start_iso and end_iso:
        try:
            s = date.fromisoformat(start_iso)
            e = date.fromisoformat(end_iso)
        except ValueError:
            return []
        if e < today or s > horizon_end:
            return []
        out = []
        cur = max(s, today)
        end = min(e, horizon_end)
        while cur <= end:
            out.append(cur.isoformat())
            cur += timedelta(days=1)
        return out

    # Recurring patterns
    if schedule == "daily":
        # 1 entry today, 1 in ~7 days (anchor + future), to avoid flooding
        # Better: emit today + every 3rd day up to horizon
        return [(today + timedelta(days=offset)).isoformat()
                for offset in (0, 3, 6, 9, 12) if (today + timedelta(days=offset)) <= horizon_end]

    if schedule == "weekly":
        # 2 entries: today (if applicable) + 7 days
        out = []
        for offset in (0, 7):
            d = today + timedelta(days=offset)
            if d <= horizon_end:
                out.append(d.isoformat())
        return out

    if schedule == "weekend":
        # Next two Saturdays
        out = []
        days_ahead_sat = (5 - today.weekday()) % 7
        if days_ahead_sat == 0:
            days_ahead_sat = 7
        first_sat = today + timedelta(days=days_ahead_sat)
        if first_sat <= horizon_end:
            out.append(first_sat.isoformat())
        if first_sat + timedelta(days=7) <= horizon_end:
            out.append((first_sat + timedelta(days=7)).isoformat())
        return out

    if schedule == "monthly":
        # 1 entry at horizon midpoint
        mid = today + timedelta(days=horizon_days // 2)
        return [mid.isoformat()]

    # Default: today only
    return [today.isoformat()]


def load_curated_events(horizon_days: int = 14) -> list[dict]:
    """Load curated recurring events from JSON and expand to concrete dates."""
    if not RECURRING_PATH.exists():
        return []
    try:
        with open(RECURRING_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    events: list[dict] = []
    for entry in data.get("recurring", []):
        venue_name = entry.get("venue_name", "")
        if not venue_name:
            continue
        schedule = entry.get("schedule", "weekly")
        title = entry.get("title", "")
        description = entry.get("description", "")
        source_url = entry.get("source_url") or ""
        commune = entry.get("commune", "Chamonix")
        start_iso = entry.get("start_date")
        end_iso = entry.get("end_date")
        time_val = entry.get("time")  # optional time slot, e.g. "17:00-19:00"

        dates = _schedule_to_dates(schedule, start_iso, end_iso, horizon_days)
        for d in dates:
            events.append({
                "title": title,
                "start_date": d,
                "venue_name": venue_name,
                "commune": commune,
                "description": description,
                "source_url": source_url,
                "category": "nightlife",
                "_source_kind": "curated",
                "confidence": 0.55,
                "time": time_val,
            })

    return events


def run(dry_run: bool = False, horizon_days: int = 14):
    start = datetime.now(timezone.utc)
    print(f"Checking {len(VENUES)} nightlife venues", file=sys.stdout)

    scraped_events: list[dict] = []
    venue_metadata: list[dict] = []

    with httpx.Client() as client:
        for venue in VENUES:
            name, commune, website, phone, address = venue
            meta = {
                "name": name,
                "commune": commune,
                "website": website or None,
                "phone": phone or None,
                "address": address or None,
                "status": "no_website" if not website else "website_found",
                "features": {},
                "events_found": 0,
            }

            if website:
                print(f"  Checking {name} ({website})...", file=sys.stdout)
                try:
                    events = scrape_venue_events(website, name, client)
                    for ev in events:
                        ev["category"] = "nightlife"
                        ev["commune"] = commune
                        ev["description"] = ev.get("description") or ""
                        ev["_source_kind"] = "scraped"
                        ev["confidence"] = 0.7
                        meta["events_found"] += 1
                    if events:
                        scraped_events.extend(events)
                        meta["status"] = "scraped"
                        print(f"    Found {len(events)} event(s)", file=sys.stdout)
                    else:
                        meta["status"] = "static_site"
                except Exception as e:
                    print(f"    ERROR: {e}", file=sys.stdout)
                    meta["status"] = "unreachable"
            else:
                print(f"  {name} — no website", file=sys.stdout)

            venue_metadata.append(meta)

    curated_events = load_curated_events(horizon_days)
    print(f"\n  Curated recurring events (expanded): {len(curated_events)}", file=sys.stdout)

    # Combine: scraped wins on (venue, date) collision, curated fills gaps
    scraped_keys = {(e["venue_name"].lower(), e["start_date"]) for e in scraped_events}
    combined = list(scraped_events)
    for e in curated_events:
        key = (e["venue_name"].lower(), e["start_date"])
        if key not in scraped_keys:
            combined.append(e)

    # Dedupe same (venue, date) within combined
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for e in combined:
        key = (e["venue_name"].lower(), e["start_date"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    deduped.sort(key=lambda e: (e.get("start_date", ""), e.get("venue_name", "")))

    venues_json = [
        {
            "name": v["name"],
            "commune": v["commune"],
            "website": v["website"],
            "phone": v["phone"],
            "address": v["address"],
            "status": v["status"],
        }
        for v in venue_metadata
    ]

    by_source = {"scraped": len(scraped_events), "curated": len(curated_events)}
    print(f"\n  Summary:", file=sys.stdout)
    print(f"    Total venues: {len(VENUES)}", file=sys.stdout)
    print(f"    Venues with websites: {sum(1 for v in VENUES if v[2])}", file=sys.stdout)
    print(f"    Scraped events: {by_source['scraped']}", file=sys.stdout)
    print(f"    Curated events: {by_source['curated']}", file=sys.stdout)
    print(f"    Combined (deduped): {len(deduped)}", file=sys.stdout)

    if dry_run:
        print(f"\n  DRY RUN - would export {len(venues_json)} venues, {len(deduped)} events", file=sys.stdout)
        print(f"\n  Venue details:", file=sys.stdout)
        for v in venue_metadata:
            icon = {"website_found": "🌐", "scraped": "✅", "static_site": "🟡", "unreachable": "❌", "no_website": "📝"}.get(v["status"], "❓")
            print(f"    {icon} {v['name'][:35]:35s} | {v['status']:15s} | events: {v['events_found']}", file=sys.stdout)
        print(f"\n  First 15 events:", file=sys.stdout)
        for e in deduped[:15]:
            print(f"    {e['start_date']} | {e['venue_name'][:30]:30} | {e.get('_source_kind','?'):8} | {e['title'][:60]}", file=sys.stdout)
        return

    # Write to SQLite storage layer (T44 fix — replaces old events.json direct write)
    from scripts.storage import get_storage  # noqa: E402
    storage = get_storage()

    # Set source_id on all events
    for e in deduped:
        e["source_id"] = SOURCE_ID
        e["category"] = e.get("category", "nightlife")
        e["commune"] = e.get("commune", "Chamonix")
        e["status"] = "pending_review"  # storage layer promotes to published if >= threshold

    count = storage.upsert_events(SOURCE_ID, deduped)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n  Storage: upserted {count} events via source_id={SOURCE_ID}", file=sys.stdout)
    print(f"\n  Summary:", file=sys.stdout)
    print(f"    Total venues: {len(VENUES)}", file=sys.stdout)
    print(f"    Venues with websites: {sum(1 for v in VENUES if v[2])}", file=sys.stdout)
    print(f"    Scraped events: {by_source['scraped']}", file=sys.stdout)
    print(f"    Curated events: {by_source['curated']}", file=sys.stdout)
    print(f"    Combined (deduped): {len(deduped)}", file=sys.stdout)
    print(f"\nDone in {elapsed:.1f}s", file=sys.stdout)


def main():
    parser = argparse.ArgumentParser(description="Scrape + curate Chamonix nightlife events")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    parser.add_argument("--horizon-days", type=int, default=14, help="Days ahead to expand recurring events (default 14)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, horizon_days=args.horizon_days)


if __name__ == "__main__":
    main()