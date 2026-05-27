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

from scripts.models import Event

logger = logging.getLogger(__name__)
SOURCE_ID = "chamonix_nightlife"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

VENUES = [
    ("Big Mountain Basecamp", "Chamonix", "https://www.bigmtnbrew.co/chamonix-basecamp/", "", "365 Avenue Ravanel le Rouge"),
    ("Le Solerey Brewpub", "Chamonix", "https://lesolereybrewpub.com/", "+33 4 56 37 46 85", "81 Avenue des Alpages"),
    ("South Bar", "Chamonix", "https://south-bar-chamonix.edan.io/", "+33 6 89 17 80 33", ""),
    ("The Beckett & Wilde", "Chamonix", "https://www.thebeckettandwilde.com/", "", ""),
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
    ("Amnesia", "Chamonix", "", "", "needs field verify"),
    ("Le Garage", "Chamonix", "", "", "needs field verify"),
]


def check_venue_page(url: str, client: httpx.Client) -> dict | None:
    try:
        resp = client.get(url, follow_redirects=True, timeout=15.0)
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")
    body = soup.get_text(" ", strip=True).lower()

    info = {
        "has_event_page": False,
        "has_live_music": "live music" in body or "livemusic" in body or "concert" in body,
        "has_dj": "dj" in body,
        "has_happy_hour": "happy hour" in body,
        "has_regular_schedule": False,
        "found_event_links": [],
        "page_title": soup.title.string.strip()[:80] if soup.title else "",
    }

    for a in soup.select("a[href]"):
        href = a.get("href", "").lower()
        if any(w in href for w in ["event", "agenda", "calendar", "concert", "live", "music", "whats-on"]):
            info["found_event_links"].append((a.get("href", ""), a.get_text(strip=True)[:60]))
            info["has_event_page"] = True

    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
            "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    day_count = sum(1 for d in days if d in body)
    if day_count >= 3:
        info["has_regular_schedule"] = True

    return info


def scrape_venue_events(url: str, venue_name: str, client: httpx.Client) -> list[dict]:
    events = []
    try:
        resp = client.get(url, follow_redirects=True, timeout=15.0)
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return events

    soup = BeautifulSoup(html, "html.parser")
    body_text = soup.get_text(" ", strip=True)

    date_patterns = [
        r"(\d{1,2})\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\s+(\d{4})",
        r"(\d{1,2})/(\d{1,2})/(\d{4})",
        r"(\d{1,2})-(\d{1,2})-(\d{4})",
        r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})",
    ]

    month_map = {
        "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
        "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    today = datetime.now().strftime("%Y-%m-%d")

    for sel in [".event", ".event-item", ".calendar-item", ".schedule-item", "article", "li"]:
        for el in soup.select(sel):
            el_text = el.get_text(" ", strip=True)
            for pat in date_patterns:
                m = re.search(pat, el_text, re.IGNORECASE)
                if m:
                    groups = m.groups()
                    try:
                        if len(groups) == 3 and groups[1].isalpha() and len(groups[1]) > 3:
                            day, month_name, year = groups
                            month = month_map.get(month_name.lower(), 0)
                            if month:
                                iso = f"{year}-{month:02d}-{int(day):02d}"
                                if iso >= today:
                                    events.append({
                                        "title": el_text[:120],
                                        "start_date": iso,
                                        "venue_name": venue_name,
                                        "source_url": url,
                                    })
                        elif len(groups) == 3 and groups[1].isalpha():
                            day, month_abbr, year = groups
                            month = month_map.get(month_abbr.lower(), 0)
                            if month:
                                iso = f"{year}-{month:02d}-{int(day):02d}"
                                if iso >= today:
                                    events.append({
                                        "title": el_text[:120],
                                        "start_date": iso,
                                        "venue_name": venue_name,
                                        "source_url": url,
                                    })
                        else:
                            day, month, year = groups[0], groups[1], groups[2]
                            iso = f"{year}-{int(month):02d}-{int(day):02d}"
                            if iso >= today:
                                events.append({
                                    "title": el_text[:120],
                                    "start_date": iso,
                                    "venue_name": venue_name,
                                    "source_url": url,
                                })
                    except (ValueError, IndexError):
                        pass

    return events


def run(dry_run: bool = False):
    start = datetime.now(timezone.utc)
    print(f"Checking {len(VENUES)} nightlife venues", file=sys.stdout)

    all_events = []
    venue_metadata = []

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
                info = check_venue_page(website, client)
                if info:
                    meta["features"] = info
                    meta["status"] = "scraped" if info.get("has_event_page") or info.get("has_live_music") else "static_site"
                    events = scrape_venue_events(website, name, client)
                    for ev in events:
                        ev["category"] = "nightlife"
                        ev["commune"] = commune
                        ev["description"] = ""
                        meta["events_found"] += 1
                    if events:
                        all_events.extend(events)
                        print(f"    Found {len(events)} event(s)", file=sys.stdout)
                else:
                    meta["status"] = "unreachable"
            else:
                print(f"  {name} — no website (OSM confirmed)", file=sys.stdout)

            venue_metadata.append(meta)

    all_events.sort(key=lambda e: e.get("start_date", ""))

    venues_json = [
        {
            "name": v["name"],
            "commune": v["commune"],
            "website": v["website"],
            "phone": v["phone"],
            "address": v["address"],
            "status": v["status"],
            "has_event_page": v["features"].get("has_event_page", False) if v["features"] else False,
            "has_live_music": v["features"].get("has_live_music", False) if v["features"] else False,
            "has_regular_schedule": v["features"].get("has_regular_schedule", False) if v["features"] else False,
        }
        for v in venue_metadata
    ]

    with_sites = sum(1 for v in VENUES if v[2])
    scrapeable = sum(1 for v in venue_metadata if v["status"] not in ("no_website", "unreachable"))
    with_schedule = sum(1 for v in venue_metadata if v["features"] and v["features"].get("has_regular_schedule"))
    with_livemusic = sum(1 for v in venue_metadata if v["features"] and v["features"].get("has_live_music"))
    total_events = len(all_events)

    print(f"\n  Summary:", file=sys.stdout)
    print(f"    Total venues: {len(VENUES)}", file=sys.stdout)
    print(f"    Venues with websites: {with_sites}", file=sys.stdout)
    print(f"    Venues scrapeable: {scrapeable}", file=sys.stdout)
    print(f"    Venues with live music: {with_livemusic}", file=sys.stdout)
    print(f"    Venues with schedule info: {with_schedule}", file=sys.stdout)
    print(f"    Specific events extracted: {total_events}", file=sys.stdout)

    if dry_run:
        print(f"\n  DRY RUN - would export {len(venues_json)} venues, {total_events} events", file=sys.stdout)
        print(f"\n  Venue details:", file=sys.stdout)
        for v in venue_metadata:
            icon = {"website_found": "\U0001f310", "scraped": "\u2705", "static_site": "\U0001f7e1", "unreachable": "\u274c", "no_website": "\U0001f4dd"}.get(v["status"], "\u2753")
            print(f"    {icon} {v['name'][:35]:35s} | {v['status']:15s} | events: {v['events_found']}", file=sys.stdout)
    else:
        existing_path = DATA_DIR / "events.json"
        existing_data = []
        if existing_path.exists():
            try:
                with open(existing_path) as f:
                    existing_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        existing_other = [e for e in existing_data if e.get("source_id") != SOURCE_ID]
        now_iso = datetime.now(timezone.utc).isoformat()
        combined = existing_other + [{
            "id": "",
            "title": e["title"],
            "description": e.get("description", ""),
            "start_date": e["start_date"],
            "end_date": None,
            "time": None,
            "category": "nightlife",
            "commune": e.get("commune", "Chamonix"),
            "source_id": SOURCE_ID,
            "source_url": e.get("source_url", ""),
            "image_url": None,
            "price": None,
            "venue_name": e.get("venue_name", ""),
            "status": "published",
            "confidence": 0.7,
            "created_at": now_iso,
            "updated_at": now_iso,
        } for e in all_events]

        combined.sort(key=lambda e: (e.get("start_date", "") or "", e.get("title", "")))

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / "events.json", "w", encoding="utf-8") as f:
            json.dump(combined, f, indent=2, ensure_ascii=False)

        with open(DATA_DIR / "venues.json", "w", encoding="utf-8") as f:
            json.dump(venues_json, f, indent=2, ensure_ascii=False)

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        print(f"\nExported {total_events} nightlife events across {len(venues_json)} venues in {elapsed:.1f}s", file=sys.stdout)

    print(f"\nDone.", file=sys.stdout)


def main():
    parser = argparse.ArgumentParser(description="Scrape nightlife venues in Chamonix")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
