from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from scripts.models import Event, Venue
from scripts.storage import get_storage
from scripts.sources import get_source  # T13
from scripts.scoring import compute_confidence  # T14

logger = logging.getLogger(__name__)

BASE_URL = "https://www.chamonix.com"
LISTING_URL = f"{BASE_URL}/evenements/evenements-et-manifestations"
SOURCE_ID = "chamonix_com"
# T13: confidence baseline derived from sources.yaml trust_level
_source = get_source(SOURCE_ID)
CONFIDENCE = _source.confidence_baseline() if _source else 1.0

COMMUNE_MAP = {
    "chamonix-mont-blanc": "Chamonix",
    "argentière": "Argentiere",
    "les houches": "Les Houches",
    "servoz": "Servoz",
    "vallorcine": "Vallorcine",
}

CATEGORY_KEYWORDS: list[tuple[list[str], str]] = [
    (["concert", "chorale", "chœur", "choeur", "musique", "orchestre"], "concert"),
    (["théâtre", "theatre", "spectacle"], "theatre"),
    (["sport", "marathon", "escalade", "ski", "randonnée", "vélo", "course"], "sport"),
    (["marché", "marche"], "market"),
    (["exposition", "photo", "peinture", "musée"], "exhibition"),
    (["soirée", "bar", "club", "concert"], "nightlife"),
    (["enfant", "famille", "jeune public", "jeu"], "family"),
]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def fetch_page(url: str, client: httpx.Client) -> str:
    resp = client.get(url, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return resp.text


def extract_event_links(html: str) -> list[tuple[str, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str, str]] = []
    seen_urls: set[str] = set()

    for item in soup.select("div.objet-touristique"):
        # Pick the event link (not wishlist, not contact, not phone).
        # Only ACTUAL events qualify: /agenda/evenements-et-manifestations/
        # (dated events) and /animations-et-evenements-* (commune events).
        # /a-voir-a-faire/ is the "Things to do / leisure" section (recurring
        # bookable activities like guided tours, spas) — NOT dated events, so it
        # must NOT be treated as an event source (2026-08-07).
        link = (
            item.select_one("a[href*='/agenda/']")
            or item.select_one("a[href*='/animations-et']")
        )
        if not link:
            continue
        href = link.get("href", "")
        if not href:
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)
        title = link.get_text(strip=True)
        if not title or len(title) < 3:
            continue

        item_text = item.get_text(" ", strip=True)
        date_str = ""
        # Match date patterns found on the site
        for pat in [
            r"(\d{2}/\d{2}-\d{2}/\d{2}/\d{2})",  # 13/05-24/06/26
            r"(\d{2}-\d{2}/\d{2}/\d{2})",          # 01-01/11/26 (same day)
            r"(\d{2}/\d{2}/\d{4})",                    # 27/05/2026 (4-digit year)
            r"(\d{2}/\d{2}/\d{2})",                    # 27/05/26 (2-digit year, after 4-digit)
        ]:
            m = re.search(pat, item_text)
            if m:
                date_str = m.group(1)
                break
        results.append((title, date_str, full_url))

    return results


def parse_date_range(date_text: str) -> tuple[str, str | None]:
    date_text = date_text.strip()
    if not date_text:
        return ("", None)

    # Single exact date: 27/05/2026
    if re.match(r"^\d{2}/\d{2}/\d{4}$", date_text):
        d = datetime.strptime(date_text, "%d/%m/%Y")
        return (d.strftime("%Y-%m-%d"), None)

    # Single short date: 27/05/26
    if re.match(r"^\d{2}/\d{2}/\d{2}$", date_text):
        d = datetime.strptime(date_text, "%d/%m/%y")
        return (d.strftime("%Y-%m-%d"), None)

    # Range: DD/MM-DD/MM/YY  e.g. 13/05-24/06/26
    m = re.match(r"^(\d{2})/(\d{2})-(\d{2})/(\d{2})/(\d{2})$", date_text)
    if m:
        century = "20"  # assume 20xx
        start = datetime.strptime(f"{m.group(1)}/{m.group(2)}/{century}{m.group(5)}", "%d/%m/%Y")
        end = datetime.strptime(f"{m.group(3)}/{m.group(4)}/{century}{m.group(5)}", "%d/%m/%Y")
        return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    # Range: DD-DD/MM/YY  e.g. 01-01/11/26 (same day range)
    m = re.match(r"^(\d{2})-(\d{2})/(\d{2})/(\d{2})$", date_text)
    if m:
        century = "20"
        start = datetime.strptime(f"{m.group(1)}/{m.group(3)}/{century}{m.group(4)}", "%d/%m/%Y")
        end = datetime.strptime(f"{m.group(2)}/{m.group(3)}/{century}{m.group(4)}", "%d/%m/%Y")
        return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    return (date_text, None)


def extract_commune(text: str) -> str:
    t = text.strip().lower()
    for key, val in COMMUNE_MAP.items():
        if key in t:
            return val
    if "chamonix" in t:
        return "Chamonix"
    return "Chamonix"


def classify_category(title: str, description: str = "") -> str:
    text = (title + " " + description).lower()
    for keywords, cat in CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return cat
    return "other"


def parse_event_detail(url: str, client: httpx.Client) -> dict:
    html = fetch_page(url, client)
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one("h1") or soup.select_one("h2")
    title = title_el.get_text(strip=True) if title_el else ""

    desc_el = soup.select_one(".content .field--name-body, .description, #presentation, .section-presentation")
    description = ""
    if desc_el:
        description = desc_el.get_text(strip=True)

    commune = "Chamonix"
    commune_el = soup.select_one(".field--name-field-ville, .commune, .lieu")
    if commune_el:
        commune = extract_commune(commune_el.get_text(strip=True))
    else:
        body_text = soup.get_text()
        for key, val in COMMUNE_MAP.items():
            if key in body_text.lower():
                commune = val
                break

    date_text = ""
    date_el = soup.select_one(
        ".field--name-field-date-debut, "
        ".field--name-field-date, "
        ".date-display-single, "
        ".field--name-field-dates, "
        ".dates-ouvertures, "
        ".section-dates"
    )
    if date_el:
        date_text = date_el.get_text(strip=True)
    if not date_text:
        date_el = soup.select_one("[property='schema:startDate'], [itemprop='startDate']")
        if date_el:
            date_text = date_el.get("content", date_el.get_text(strip=True))

    start_date, end_date = parse_date_range(date_text)

    time_str = None
    time_el = soup.select_one(
        ".field--name-field-heure, .field--name-field-horaire, "
        "[property='schema:startTime'], [itemprop='startTime']"
    )
    if time_el:
        time_str = time_el.get_text(strip=True) or time_el.get("content")
    if not time_str and "horaire" in date_text.lower():
        time_match = re.search(r"(\d{1,2}h\d{2})(?:[-à](\d{1,2}h\d{2}))?", date_text)
        if time_match:
            time_str = time_match.group(0).replace("h", ":")

    img_url = None
    img_el = soup.select_one(
        "meta[property='og:image'], "
        "meta[name='twitter:image'], "
        ".image-principale img, "
        ".field--name-field-image img, "
        "picture img"
    )
    if img_el:
        src = img_el.get("content") or img_el.get("src") or ""
        if src and not src.startswith("http"):
            src = urljoin(BASE_URL, src)
        img_url = src or None

    price_str = None
    price_el = soup.select_one(
        ".field--name-field-tarif, .tarifs, .section-tarifs, .price"
    )
    if price_el:
        price_str = price_el.get_text(strip=True)[:200]

    venue_name = None
    venue_el = soup.select_one(".field--name-field-lieu, .lieu, .adresse, .location, .section-localisation")
    if venue_el:
        venue_name = venue_el.get_text(strip=True)[:100]

    category = classify_category(title, description)

    return {
        "title": title,
        "description": description,
        "start_date": start_date,
        "end_date": end_date,
        "time": time_str,
        "commune": commune,
        "category": category,
        "image_url": img_url,
        "price": price_str,
        "venue_name": venue_name,
        "source_url": url,
    }


def parse_listing_page(html: str, client: httpx.Client, dry_run: bool) -> list[dict]:
    links = extract_event_links(html)
    print(f"  Found {len(links)} event links on listing page", file=sys.stdout)

    events_raw = []
    for title, date_str, url in links:
        # Start with listing-page data
        ev = {
            "title": title,
            "start_date": parse_date_range(date_str)[0],
            "end_date": parse_date_range(date_str)[1],
            "commune": "Chamonix",
            "category": classify_category(title),
            "source_url": url,
            "description": "",
            "time": None,
            "image_url": None,
            "price": None,
            "venue_name": None,
        }
        if not dry_run:
            try:
                print(f"    Fetching detail: {title[:60]}...", file=sys.stdout)
                detail = parse_event_detail(url, client)
                # Override with detail data where available
                if detail.get("start_date"):
                    ev["start_date"] = detail["start_date"]
                if detail.get("end_date"):
                    ev["end_date"] = detail["end_date"]
                if detail.get("description"):
                    ev["description"] = detail["description"]
                if detail.get("image_url"):
                    ev["image_url"] = detail["image_url"]
                if detail.get("venue_name"):
                    ev["venue_name"] = detail["venue_name"]
                if detail.get("time"):
                    ev["time"] = detail["time"]
                if detail.get("price"):
                    ev["price"] = detail["price"]
            except Exception as e:
                print(f"    ERROR fetching {url}: {e}", file=sys.stderr)
        events_raw.append(ev)

    return events_raw


def normalize(raw: dict) -> Event:
    title = (raw.get("title") or "").strip()
    start_date = raw.get("start_date") or ""
    end_date = raw.get("end_date")
    commune = raw.get("commune", "Chamonix")
    category = raw.get("category", "other")
    source_url = raw.get("source_url", "")

    ev = Event(
        title=title,
        description=(raw.get("description") or "").strip(),
        start_date=start_date,
        end_date=end_date,
        time=raw.get("time"),
        commune=commune,
        category=category,
        source_id=SOURCE_ID,
        source_url=source_url,
        image_url=raw.get("image_url"),
        price=raw.get("price"),
        status="published",
        confidence=CONFIDENCE,  # placeholder, recomputed below
    )
    # T14: trust × parse_quality × completeness
    ev.confidence = compute_confidence(SOURCE_ID, ev.to_dict())
    return ev


def deduplicate(events: list[Event]) -> list[Event]:
    seen: dict[str, Event] = {}
    for ev in events:
        key = (
            ev.title.lower().strip(),
            ev.start_date[:10] if ev.start_date else "",
            ev.commune.lower(),
        )
        if key in seen:
            existing = seen[key]
            if ev.confidence > existing.confidence:
                seen[key] = ev
        else:
            seen[key] = ev
    return list(seen.values())


def extract_venues(events: list[Event]) -> list[Venue]:
    venue_map: dict[str, Venue] = {}
    for ev in events:
        vid = ev.get("venue_id") if isinstance(ev, dict) else ev.venue_id
        commune = ev.get("commune", "Chamonix") if isinstance(ev, dict) else ev.commune
        if vid and vid not in venue_map:
            venue_map[vid] = Venue(
                id=vid,
                name=vid.replace("-", " ").title(),
                commune=commune,
                source_id=SOURCE_ID,
            )
    return list(venue_map.values())


def export_json(events: list[Event], venues: list[Venue]):
    # T10: SQLite canonical, JSON is build artefact only.
    # T04: REMOVED venues.json write — venues are seeded by T17 (Phase 3).
    events_path = DATA_DIR / "events.json"  # kept for backwards compat / inspection

    def as_dict(e):
        return e.to_dict() if hasattr(e, "to_dict") else e

    get_storage().upsert_events(SOURCE_ID, [as_dict(ev) for ev in events])
    if venues:
        # Diagnostic only — chamonix_com.extract_venues() returns [] today
        # because venue_id is never set on events. Don't write to disk.
        print(f"  NOTE: chamonix_com produced {len(venues)} venues; ignored (T04)", file=sys.stderr)


def merge_with_existing(new_events: list[Event]) -> list[Event]:
    existing_path = DATA_DIR / "events.json"
    if not existing_path.exists():
        return new_events
    try:
        with open(existing_path) as f:
            existing_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return new_events
    other_source = [e for e in existing_data if e.get("source_id") != "chamonix_com"]
    combined_events = [e.to_dict() for e in new_events] + other_source
    combined_events.sort(key=lambda e: (e.get("start_date", "") or "", e.get("title", "")))
    result = []
    for e in combined_events:
        if isinstance(e, Event):
            result.append(e)
        else:
            result.append(e)
    return result


def run(dry_run: bool = False):
    start = datetime.now(timezone.utc)

    print(f"Scraping {LISTING_URL}", file=sys.stdout)

    try:
        with httpx.Client() as client:
            html = fetch_page(LISTING_URL, client)
            raw_events = parse_listing_page(html, client, dry_run)
    except httpx.HTTPStatusError as e:
        print(f"HTTP error: {e.response.status_code} {e}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Request failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

    events = [normalize(r) for r in raw_events]
    events = deduplicate(events)

    for ev in events:
        if not ev.start_date:
            print(f"  WARN: missing start_date for '{ev.title}'", file=sys.stderr)
            ev.status = "pending_review"
            ev.confidence = min(ev.confidence, 0.5)

    events.sort(key=lambda e: e.start_date)

    events = merge_with_existing(events)

    venues = extract_venues(events)

    if dry_run:
        print(file=sys.stdout)
        print(f"  DRY RUN - would write {len(events)} events, {len(venues)} venues", file=sys.stdout)
        print(file=sys.stdout)
        for ev in events:
            print(
                f"  - {ev.start_date or '???'} | {ev.category:12s} | {ev.title[:70]}",
                file=sys.stdout,
            )
    else:
        export_json(events, venues)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        print(f"\nExported {len(events)} events, {len(venues)} venues in {elapsed:.1f}s", file=sys.stdout)

    print(f"\nDone. Total: {len(events)} events, {len(venues)} venues", file=sys.stdout)


def main():
    parser = argparse.ArgumentParser(description="Scrape events from chamonix.com")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
