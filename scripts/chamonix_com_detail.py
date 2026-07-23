#!/usr/bin/env python3
"""Enrich chamonix.com events with detail page data (httpx-only).

T12 replacement for the old Playwright-based chamonix_com_detail.py.
Fetches event detail pages from chamonix.com via httpx + BeautifulSoup
and enriches existing events in SQLite with descriptions, images, dates.

Uses the sitemap to discover event URLs (deterministic, no JS needed).
"""

import json, os, re, sys
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SITEMAP_INDEX = "https://www.chamonix.com/sitemap.xml"
USER_AGENT = "Mozilla/5.0 (compatible; chamonix-events/1.0; +https://chamonix-events.example)"
TIMEOUT = 20.0
MAX_PAGES = 10  # max sitemap pages to scan

# ---------------------------------------------------------------------------
# URL discovery via sitemap
# ---------------------------------------------------------------------------

def get_sitemap_pages(client: httpx.Client) -> list[str]:
    """Fetch the sitemap index and return all sub-sitemap page URLs."""
    resp = client.get(SITEMAP_INDEX, timeout=TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "xml")
    locs = soup.find_all("loc")
    urls = [loc.get_text(strip=True) for loc in locs if loc.get_text(strip=True)]
    # Filter to sitemap pages only (we want the ones with event URLs)
    return [u for u in urls if "sitemap.xml?page=" in u]


def get_event_urls_from_sitemap(client: httpx.Client, sitemap_url: str) -> list[str]:
    """Extract event detail URLs from a single sitemap page."""
    # Normalize to https
    url = sitemap_url.replace("http://", "https://")
    try:
        resp = client.get(url, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "xml")
        urls = set()
        for loc in soup.find_all("loc"):
            url = loc.get_text(strip=True)
            if "/agenda/evenements-et-manifestations/" in url:
                urls.add(url)
        return sorted(urls)
    except Exception as e:
        print(f"  [warn] failed to fetch sitemap {sitemap_url}: {e}", file=sys.stderr)
        return []


def discover_event_urls(client: httpx.Client) -> list[str]:
    """Discover all event detail URLs from the sitemap."""
    sitemap_pages = get_sitemap_pages(client)
    if not sitemap_pages:
        print("  [warn] no sitemap pages found, falling back to listing page")
        return _fallback_listing_urls(client)

    all_urls: list[str] = []
    for i, sp in enumerate(sitemap_pages[:MAX_PAGES]):
        urls = get_event_urls_from_sitemap(client, sp)
        if urls:
            print(f"  sitemap page {i+1}: {len(urls)} event URLs")
            all_urls.extend(urls)
    return all_urls


def _fallback_listing_urls(client: httpx.Client) -> list[str]:
    """Fallback: scrape the listing page for event URLs (less reliable)."""
    LISTING_URL = "https://www.chamonix.com/evenements/evenements-et-manifestations"
    resp = client.get(LISTING_URL, timeout=TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    urls = set()
    for a in soup.find_all("a", href=True):
        h = a["href"]
        # Event detail URLs contain these patterns
        if "/agenda/evenements-et-manifestations/" in h or re.search(r"/evenements/[a-z]", h):
            if h.startswith("/"):
                h = "https://www.chamonix.com" + h
            urls.add(h)
    return sorted(urls)


# ---------------------------------------------------------------------------
# Detail page extraction
# ---------------------------------------------------------------------------

def extract_detail(client: httpx.Client, url: str) -> dict:
    """Fetch a single event detail page and extract fields."""
    result: dict = {}
    try:
        resp = client.get(url, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"    [warn] fetch failed: {e}")
        return result

    soup = BeautifulSoup(resp.text, "html.parser")

    # Title
    h1 = soup.find("h1")
    if h1:
        result["title"] = h1.get_text(strip=True)

    # Village / commune
    ville = soup.find("div", class_="ville")
    if ville:
        txt = ville.get_text(strip=True)
        txt = txt.replace("à ", "").strip()
        if txt:
            result["ville"] = txt

    # Description from the "presentation" tab
    pres_div = soup.find("div", class_="onglet-content", attrs={"data-onglet": "presentation"})
    if pres_div:
        inner = pres_div.find("div")
        if inner:
            # Get all <p> text
            paragraphs = inner.find_all("p")
            desc = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            # Fallback: entire div text
            if not desc:
                desc = inner.get_text(strip=True)
            if desc and len(desc) > 10:
                result["description"] = desc

    # Image: find the first large image with sit/images in path
    img = soup.find("img", src=lambda s: s and "/sit/images/" in s if s else None)
    if img:
        src = img.get("src", "")
        if src:
            result["image_url"] = "https://www.chamonix.com" + src if src.startswith("/") else src

    # Dates from the "ouvertures" tab
    dates_div = soup.find("div", class_="onglet-content", attrs={"data-onglet": "ouvertures"})
    if dates_div:
        dates_text = dates_div.get_text(strip=True)
        if dates_text:
            result["dates_text"] = dates_text
            # Try to parse structured dates
            _parse_french_dates(result, dates_text)

    # Address from the "localisation" tab
    loc_div = soup.find("div", class_="onglet-content", attrs={"data-onglet": "localisation"})
    if loc_div:
        addr = loc_div.find("div", class_="adresse")
        if addr:
            result["address"] = " ".join(addr.stripped_strings)

    # Website link
    site_link = soup.find("a", class_="site")
    if site_link and site_link.get("href"):
        result["website_url"] = site_link["href"]

    # Ticket link
    ticket_link = soup.find("a", class_="bouton", href=lambda h: h and "billetweb" in h)
    if not ticket_link:
        ticket_link = soup.find("a", href=lambda h: h and "billetweb" in h)
    if ticket_link and ticket_link.get("href"):
        result["ticket_url"] = ticket_link["href"]

    return result


MONTHS_FR = {
    "janvier": "01", "février": "02", "mars": "03", "avril": "04",
    "mai": "05", "juin": "06", "juillet": "07", "août": "08",
    "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12",
}


def _parse_french_dates(result: dict, text: str):
    """Parse French date strings like 'Du vendredi 10 au dimanche 12 juillet 2026'."""
    # Pattern: Du <day> <date> au <day> <date> <month> <year>
    m = re.search(
        r"Du\s+\w+\s+(\d+)\s+au\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})",
        text, re.IGNORECASE
    )
    if m:
        start_day, end_day, month_name, year = m.group(1), m.group(2), m.group(3), m.group(4)
        month_num = MONTHS_FR.get(month_name.lower())
        if month_num:
            result["start_date"] = f"{year}-{month_num}-{int(start_day):02d}"
            result["end_date"] = f"{year}-{month_num}-{int(end_day):02d}"
            return

    # Pattern: Du <day> <date> <month> <year> au <day> <date> <month> <year>
    m = re.search(
        r"Du\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})\s+au\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})",
        text, re.IGNORECASE
    )
    if m:
        sd, sm, sy, ed, em, ey = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
        sm_num = MONTHS_FR.get(sm.lower())
        em_num = MONTHS_FR.get(em.lower())
        if sm_num and em_num:
            result["start_date"] = f"{sy}-{sm_num}-{int(sd):02d}"
            result["end_date"] = f"{ey}-{em_num}-{int(ed):02d}"
            return

    # Pattern: Le <day> <date> <month> <year> (single day)
    m = re.search(
        r"Le\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})",
        text, re.IGNORECASE
    )
    if m:
        day, month_name, year = m.group(1), m.group(2), m.group(3)
        month_num = MONTHS_FR.get(month_name.lower())
        if month_num:
            iso = f"{year}-{month_num}-{int(day):02d}"
            result["start_date"] = iso
            result["end_date"] = iso


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    """Normalize title for matching."""
    import unicodedata
    t = unicodedata.normalize("NFKD", title)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9\s]", "", t)
    return t.strip().lower()


def enrich_events_from_details(details: list[dict], existing_events: list[dict]) -> tuple[list[dict], int]:
    """Match detail pages to existing events by title and enrich missing fields.

    Returns (updated_events, count).
    """
    # Build lookup: normalized title -> detail
    lookup: dict[str, dict] = {}
    for d in details:
        t = d.get("title", "")
        if t:
            lookup[normalize_title(t)] = d

    updated = 0
    for ev in existing_events:
        key = normalize_title(ev.get("title", ""))
        if not key or key not in lookup:
            continue
        detail = lookup[key]
        changed = False
        for field in ["description", "image_url", "ville", "address", "website_url", "ticket_url"]:
            if field in detail and detail[field] and not ev.get(field):
                ev[field] = detail[field]
                changed = True
        for field in ["start_date", "end_date"]:
            if field in detail and detail[field] and not ev.get(field):
                ev[field] = detail[field]
                changed = True
        if changed:
            updated += 1
    return existing_events, updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    dry_run = "--dry-run" in sys.argv

    # Import storage
    from scripts.storage import get_storage
    from scripts.sources import get_source

    source = get_source("chamonix_com")
    if not source or not source.active:
        print("chamonix_com source is inactive — skipping detail enrichment")
        return 0

    storage = get_storage()
    existing = storage.get_events(source_id="chamonix_com")
    print(f"Existing chamonix_com events: {len(existing)}")

    if not existing:
        print("No chamonix_com events to enrich — run chamonix_com scraper first")
        return 0

    # Discover event URLs
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, verify=True) as client:
        print("Discovering event URLs from sitemap...")
        event_urls = discover_event_urls(client)
        print(f"Found {len(event_urls)} event URLs")

        if not event_urls:
            print("No event URLs found — nothing to do")
            return 0

        # Fetch detail pages
        details: list[dict] = []
        for i, url in enumerate(event_urls, 1):
            slug = url.rstrip("/").split("/")[-1][:50]
            print(f"  [{i}/{len(event_urls)}] {slug}...", end=" ", flush=True)
            detail = extract_detail(client, url)
            if detail:
                details.append(detail)
                title = detail.get("title", "?")[:40]
                desc_len = len(detail.get("description", ""))
                has_img = "Y" if detail.get("image_url") else "N"
                has_dates = "Y" if detail.get("start_date") else "N"
                print(f"title={title} desc={desc_len}c img={has_img} dates={has_dates}")
            else:
                print("no data")

    print(f"Extracted {len(details)}/{len(event_urls)} detail pages")

    if dry_run:
        for d in details[:5]:
            print(f"  {d.get('title','?')}")
            print(f"    desc: {d.get('description','')[:100]}")
            print(f"    image: {'Y' if d.get('image_url') else 'N'}")
            print(f"    dates: {d.get('start_date','?')} -> {d.get('end_date','?')}")
            print(f"    ville: {d.get('ville','?')}")
        return 0

    # Enrich existing events
    enriched, count = enrich_events_from_details(details, existing)
    print(f"Enriched: {count} events updated")

    if count > 0:
        # Write back to SQLite
        storage.upsert_events_ungated("chamonix_com", enriched)
        print(f"Written {len(enriched)} events to SQLite")
    else:
        print("No events to update")

    return 0


if __name__ == "__main__":
    sys.exit(main())