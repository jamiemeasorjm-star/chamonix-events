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

BASE_URL = "https://www.chamonix.net"
LISTING_URL = f"{BASE_URL}/english/events"
SOURCE_ID = "chamonix_net"
CONFIDENCE = 1.0

COMMUNE_MAP = {
    "chamonix": "Chamonix",
    "argentiere": "Argentiere",
    "les houches": "Les Houches",
    "servoz": "Servoz",
    "vallorcine": "Vallorcine",
}

CATEGORY_MAP = {
    "tradition & markets": "market",
    "sport & leisure": "sport",
    "cultural events & exhibitions": "exhibition",
    "music festival": "concert",
    "film festival": "exhibition",
    "children & family": "family",
    "nightlife": "nightlife",
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def fetch_page(url: str, client: httpx.Client) -> str:
    resp = client.get(url, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return resp.text


def extract_listing_events(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    for node in soup.select(".node--type-event"):
        link_el = node.select_one("h2.post-title a")
        if not link_el:
            continue
        title_span = link_el.select_one("span")
        title = (title_span or link_el).get_text(strip=True)
        href = link_el.get("href", "")
        if not title or not href:
            continue
        full_url = urljoin(BASE_URL, href) if not href.startswith("http") else href

        cat_el = node.select_one(".post-categories a")
        raw_cat = cat_el.get_text(strip=True).lower() if cat_el else ""
        category = "other"
        for key, val in CATEGORY_MAP.items():
            if key in raw_cat:
                category = val
                break

        desc_el = node.select_one(".field--name-body")
        description = desc_el.get_text(strip=True) if desc_el else ""

        img_el = node.select_one("img[data-src]")
        img_src = ""
        if img_el:
            src = img_el.get("data-src", "")
            if src and not src.startswith("http"):
                src = urljoin(BASE_URL, src)
            img_src = src

        card_text = node.get_text(" ", strip=True)

        results.append({
            "title": title,
            "url": full_url,
            "category": category,
            "description": description,
            "image_url": img_src,
            "card_text": card_text,
        })

    return results


def parse_date_from_card(text: str) -> tuple[str, str | None]:
    m = re.search(
        r"(\d{1,2}-[A-Z][a-z]{2}-\d{4})\s*to\s*(\d{1,2}-[A-Z][a-z]{2}-\d{4})",
        text,
    )
    if m:
        start = datetime.strptime(m.group(1), "%d-%b-%Y").strftime("%Y-%m-%d")
        end = datetime.strptime(m.group(2), "%d-%b-%Y").strftime("%Y-%m-%d")
        return start, end

    m = re.search(r"(\d{1,2}-[A-Z][a-z]{2}-\d{4})", text)
    if m:
        d = datetime.strptime(m.group(1), "%d-%b-%Y")
        return d.strftime("%Y-%m-%d"), None

    return "", None


def parse_detail_page(url: str, client: httpx.Client) -> dict:
    html = fetch_page(url, client)
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one("h1") or soup.select_one("h2.post-title a span")
    title = title_el.get_text(strip=True) if title_el else ""

    desc_el = soup.select_one(".node__content") or soup.select_one(".field--name-body")
    description = desc_el.get_text(strip=True) if desc_el else ""

    cat_el = soup.select_one(".post-categories a")
    raw_cat = cat_el.get_text(strip=True).lower() if cat_el else ""
    category = "other"
    for key, val in CATEGORY_MAP.items():
        if key in raw_cat:
            category = val
            break

    date_text = ""
    time_str = None
    date_el = soup.select_one(".event-datetimes")
    if date_el:
        date_text = date_el.get_text(strip=True)

    date_only_el = soup.select_one(".event-dates")
    date_only = date_only_el.get_text(strip=True) if date_only_el else ""

    time_el = soup.select_one(".event-times")
    if time_el:
        time_str = time_el.get_text(strip=True)
        time_str = re.sub(r"^\d{1,2}:\d{2}", "", time_str).strip()

    start_date, end_date = parse_date_from_card(date_text or date_only)

    venue_name = None
    venue_el = soup.select_one(".event-venue")
    if venue_el:
        venue_name = venue_el.get_text(strip=True)[:100]

    address = None
    addr_el = soup.select_one(".event-address")
    if addr_el:
        address = addr_el.get_text(strip=True)[:200]

    contact_phone = None
    contact_el = soup.select_one(".event-contact")
    if contact_el:
        phone = contact_el.get_text(strip=True)
        phone_match = re.search(r"(\+[\d\s-]{7,20})", phone)
        if phone_match:
            contact_phone = phone_match.group(1).strip()

    website = None
    web_el = soup.select_one(".event-website a")
    if web_el:
        website = web_el.get("href", "").strip()
    if not website:
        web_text_el = soup.select_one(".event-website")
        if web_text_el:
            w = web_text_el.get_text(strip=True)
            if w and "www." in w.lower():
                website = w

    img_url = None
    img_meta = soup.select_one("meta[property='og:image']")
    if img_meta:
        src = img_meta.get("content", "")
        if src:
            img_url = src

    commune = "Chamonix"
    page_text = soup.get_text().lower()
    for key, val in COMMUNE_MAP.items():
        if key in page_text:
            commune = val
            break

    return {
        "title": title,
        "description": description,
        "start_date": start_date,
        "end_date": end_date,
        "time": time_str,
        "commune": commune,
        "category": category,
        "image_url": img_url,
        "price": None,
        "venue_name": venue_name,
        "address": address,
        "contact_phone": contact_phone,
        "website": website,
        "source_url": url,
    }


def merge_with_existing(new_events: list[Event]) -> list[Event]:
    existing_path = DATA_DIR / "events.json"
    if not existing_path.exists():
        return new_events

    try:
        with open(existing_path) as f:
            existing_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return new_events

    existing_com = [e for e in existing_data if e.get("source_id") != "chamonix_net"]
    new_urls = {e.source_url for e in new_events if e.source_url}

    kept_com = [e for e in existing_com if e.get("source_url", "") not in new_urls]

    combined = [e.to_dict() for e in new_events] + kept_com
    combined.sort(key=lambda e: (e.get("start_date", "") or "", e.get("title", "")))

    return [Event(**e) if not isinstance(e, Event) else e for e in combined]


def classify_category(title: str, description: str = "") -> str:
    text = (title + " " + description).lower()
    for keywords, cat in [
        (["concert", "chorale", "choeur", "musique", "orchestre"], "concert"),
        (["theatre", "spectacle", "danse"], "theatre"),
        (["sport", "marathon", "escalade", "ski", "randonnee", "velo", "course", "freeride"], "sport"),
        (["marche", "market"], "market"),
        (["exposition", "photo", "peinture", "musee", "exhibition", "film", "festival"], "exhibition"),
        (["soiree", "bar", "club", "nightlife"], "nightlife"),
        (["enfant", "famille", "jeune public", "jeu", "family"], "family"),
    ]:
        for kw in keywords:
            if kw in text:
                return cat
    return "other"


def normalize(raw: dict, source_url: str) -> Event:
    title = (raw.get("title") or "").strip()
    start_date = raw.get("start_date") or ""
    end_date = raw.get("end_date")
    commune = raw.get("commune", "Chamonix")
    category = raw.get("category") or classify_category(title, raw.get("description", ""))

    return Event(
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
        venue_name=raw.get("venue_name"),
        status="published",
        confidence=CONFIDENCE,
    )


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


def export_json(events: list[Event]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    events_path = DATA_DIR / "events.json"
    with open(events_path, "w", encoding="utf-8") as f:
        json.dump([ev.to_dict() for ev in events], f, indent=2, ensure_ascii=False)


def run(dry_run: bool = False, fetch_detail: bool = True):
    start = datetime.now(timezone.utc)
    print(f"Scraping {LISTING_URL}", file=sys.stdout)

    try:
        with httpx.Client() as client:
            html = fetch_page(LISTING_URL, client)
            listing_events = extract_listing_events(html)
            print(f"  Found {len(listing_events)} events on listing page", file=sys.stdout)

            raw_events = []
            for ev in listing_events:
                if fetch_detail:
                    try:
                        print(f"    Fetching detail: {ev['title'][:60]}...", file=sys.stdout)
                        detail = parse_detail_page(ev["url"], client)
                        for field in ["start_date", "end_date", "description", "image_url",
                                      "time", "venue_name", "address", "contact_phone",
                                      "website", "commune"]:
                            if detail.get(field):
                                ev[field] = detail[field]
                        if detail.get("category") != "other":
                            ev["category"] = detail["category"]
                    except Exception as e:
                        print(f"    ERROR fetching detail: {e}", file=sys.stderr)
                        if not ev.get("start_date"):
                            ev["start_date"], ev["end_date"] = parse_date_from_card(ev.get("card_text", ""))
                else:
                    if not ev.get("start_date"):
                        ev["start_date"], ev["end_date"] = parse_date_from_card(ev.get("card_text", ""))

                raw_events.append(ev)

    except httpx.HTTPStatusError as e:
        print(f"HTTP error: {e.response.status_code} {e}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Request failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

    events = [normalize(r, r.get("url", "")) for r in raw_events]
    events = deduplicate(events)
    events = merge_with_existing(events)

    for ev in events:
        if not ev.start_date:
            print(f"  WARN: missing start_date for '{ev.title}'", file=sys.stderr)
            ev.status = "pending_review"
            ev.confidence = min(ev.confidence, 0.5)

    events.sort(key=lambda e: e.start_date or "")

    if dry_run:
        has_desc = sum(1 for e in events if e.description.strip())
        print(f"\n  DRY RUN - {len(events)} events ({has_desc} with descriptions)\n", file=sys.stdout)
        for ev in events:
            desc_flag = " D" if ev.description.strip() else " no-desc"
            img_flag = " I" if ev.image_url else " no-img"
            time_flag = " T" if ev.time else ""
            venue_flag = " V" if ev.venue_name else ""
            print(f"  {ev.start_date or '???'} | {ev.category:12s} | {ev.title[:50]:50s} |{desc_flag}{img_flag}{time_flag}{venue_flag}", file=sys.stdout)
    else:
        export_json(events)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        has_desc = sum(1 for e in events if e.description.strip())
        has_img = sum(1 for e in events if e.image_url)
        has_time = sum(1 for e in events if e.time)
        has_venue = sum(1 for e in events if e.venue_name)
        print(f"\nExported {len(events)} events ({has_desc}d {has_img}i {has_time}t {has_venue}v) in {elapsed:.1f}s", file=sys.stdout)

    print(f"\nDone. Total: {len(events)} events", file=sys.stdout)


def main():
    parser = argparse.ArgumentParser(description="Scrape events from chamonix.net")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    parser.add_argument("--no-detail", action="store_true", help="Skip detail page fetching")
    args = parser.parse_args()
    run(dry_run=args.dry_run, fetch_detail=not args.no_detail)


if __name__ == "__main__":
    main()
