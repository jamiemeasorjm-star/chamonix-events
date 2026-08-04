#!/usr/bin/env python3
import httpx, json, re, sys, os
from datetime import date
from bs4 import BeautifulSoup

from scripts.models import Event
from scripts.storage import get_storage
from scripts.sources import get_source  # T13
import json  # T10: still needed for parsing existing events.json on legacy callers
import os  # T10: legacy paths used by direct script invocation

URL = "https://www.allocine.fr/seance/salle_gen_csalle=P1406.html"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
EVENTS_FILE = os.path.join(DATA_DIR, "events.json")

# T13: source registry — trust_level determines confidence baseline
SOURCE_ID = "allocine_vox"
_source = get_source(SOURCE_ID)
CONFIDENCE = _source.confidence_baseline() if _source else 0.8

MONTHS_FR = {"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,"juillet":7,"aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12}

def parse_french_date(text):
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text.strip())
    if m:
        month = MONTHS_FR.get(m.group(2).lower())
        if month:
            return date(int(m.group(3)), month, int(m.group(1)))
    return None

def fetch():
    r = httpx.get(URL, timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.text

def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    venue = {"name":"Le Vox","address":"22, cours Bartavel, 74400"}
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string)
            if isinstance(d, dict) and d.get("@type")=="MovieTheater":
                venue["name"]=d.get("name",venue["name"])
                a=d.get("address",{})
                street = a.get("streetAddress", "") or ""
                postal = a.get("postalCode", "") or ""
                locality = a.get("addressLocality", "") or ""
                venue["address"] = f"{street}, {postal} {locality}".strip(", ").strip()
        except:
            pass
    events=[]
    for card in soup.find_all("div", class_="movie-card-theater"):
        title_el = card.find(["h2","h3"]) or card.find("a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        versions = card.find_all("div", class_="showtimes-version")
        showtimes = {}
        film_langs = set()
        for ver in versions:
            ver_text = ver.get_text()
            # Detect language from text like "En VF" or "En VO"
            lang = "Francais"
            vt = ver_text.lower()
            if "vo" in vt and "vf" not in vt:
                lang = "VO"
            elif "vost" in vt:
                lang = "VOST"
            elif "vfst" in vt:
                lang = "VFST"
            elif "vf" in vt:
                lang = "Francais"
            film_langs.add(lang)
            for span in ver.find_all("span", attrs={"data-showtime-time": True}):
                iso = span["data-showtime-time"]
                dt = iso[:10]
                tm = iso[11:16]
                if dt not in showtimes:
                    showtimes[dt]=[]
                showtimes[dt].append(tm)
        if not showtimes:
            continue
        dates_sorted = sorted(showtimes.keys())
        img = card.find("img")
        image_url = img.get("data-src","") or img.get("src","") if img else ""
        if "acsta.net" in image_url:
            image_url = re.sub(r"/r_\d+_\d+/", "/r_640_/", image_url)
        venue_name = venue["name"]
        events.append({
            "title": title,
            "description": f"Film screening at {venue_name}",
            "event_type": "cinema",
            "category": "Cinema",
            "source_id": "allocine_vox",
            "source_url": URL,
            "image_url": image_url,
            "venue": venue["name"],
            "address": venue["address"],
            "commune": "Chamonix",
            "start_date": dates_sorted[0],
            "end_date": dates_sorted[-1],
            "showtimes": showtimes,
            "language": "|".join(sorted(film_langs)) if len(film_langs) > 0 else "Francais",
            "voice_versions": "|".join(sorted(film_langs))
        })
    return events, venue

def merge(existing, new_events):
    existing = [e for e in existing if e.get("category")!="Cinema"]
    existing.extend(new_events)
    return existing

def _cleanup_legacy_allocine_cinema(storage=None) -> int:
    """One-off, safe, idempotent cleanup: remove any leftover invisible rows in
    the `events` table with source_id='allocine_vox' AND category='Cinema'.

    Only deletes allocine_vox cinema-category rows; everything else is
    untouched. Returns the number of rows removed (0 when already clean).
    """
    if storage is None:
        storage = get_storage()
    with storage.conn:
        cur = storage.conn.execute(
            "DELETE FROM events WHERE source_id = ? AND category = ?",
            (SOURCE_ID, "Cinema"),
        )
        return cur.rowcount


def main():
    dry = "--dry-run" in sys.argv
    html = fetch()
    events, venue = parse(html)
    venue_name = venue["name"]
    print(f"Found {len(events)} cinema events from {venue_name}")
    for ev in events:
        days=len(ev["showtimes"])
        total=sum(len(v) for v in ev["showtimes"].values())
        ev_title = ev["title"]
        print(f"  {ev_title}: {days} days, {total} screenings")
    if dry:
        print("Dry run - no changes")
        return
    # Legacy cleanup: remove leftover invisible allocine_vox Cinema rows from
    # the `events` table (idempotent — a second run removes 0 rows).
    removed = _cleanup_legacy_allocine_cinema()
    print(f"Legacy cleanup: removed {removed} allocine_vox Cinema rows from events")

    # cinema-merge: allocine_vox is now an ENRICHER of cinema_events. It ONLY
    # backfills missing posters/descriptions and NEVER writes to `events`.
    storage = get_storage()
    matched = storage.enrich_cinema(events)
    print(
        f"Enriched {matched} cinema_events rows "
        "(allocine_vox writes ONLY via enrich_cinema; events table untouched)"
    )

if __name__ == "__main__":
    main()
