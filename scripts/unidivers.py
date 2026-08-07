"""Scrape Chamonix events from Unidivers (unidivers.fr).

Unidivers is a public WordPress events site, fed in part by the Office de
Tourisme de la Vallée de Chamonix-Mont-Blanc, so it carries the same event
content that lives on the venues' Facebook pages — but anonymously scrapable.

Discovery: the WP search RSS feed `/?s=chamonix&feed=rss2` returns hundreds of
event URLs, with the ISO date embedded in each URL slug (e.g.
`...braderie-des-commercants-...-2026-08-17/`).

Enrichment: each event detail page embeds a full schema.org JSON-LD `Event`
record (name, startDate, endDate, location with geo coords + street, offers/price,
image, description).

Registered as source_id `unidivers` (trust medium-high since it mirrors the OT).
Follows the same conventions as chamonix_net.py (compute_confidence + upsert).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from xml.etree import ElementTree

import httpx

from scripts.models import Event
from scripts.storage import get_storage
from scripts.sources import get_source
from scripts.scoring import compute_confidence

BASE_URL = "https://unidivers.fr"
SEARCH = "/?s=chamonix"
RSS_URL = f"{BASE_URL}{SEARCH}&feed=rss2"
SOURCE_ID = "unidivers"
_source = get_source(SOURCE_ID)
CONFIDENCE = _source.confidence_baseline() if _source else 1.0

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# Calendar categories for the site
CATEGORY_MAP = [
    ("concert", "concert"),
    ("festival", "concert"),
    ("musique", "concert"),
    ("cinema", "exhibition"),
    ("film", "exhibition"),
    ("theatre", "theatre"),
    ("spectacle", "theatre"),
    ("exposition", "exhibition"),
    ("muse", "exhibition"),
    ("visite", "exhibition"),
    ("conférence", "other"),
    ("conference", "other"),
    ("rencontre", "other"),
    ("debat", "other"),
    ("marché", "market"),
    ("marche", "market"),
    ("foire", "market"),
    ("brocante", "market"),
    ("braderie", "market"),
    ("sport", "sport"),
    ("course", "sport"),
    ("trail", "sport"),
    ("match", "sport"),
    ("gymnastique", "sport"),
    ("enfant", "family"),
    ("famille", "family"),
    ("atelier", "family"),
    ("animation", "family"),
    ("jeune public", "family"),
]


def classify_category(text: str) -> str:
    t = text.lower()
    if re.search(r"march[ée]|foire|brocante|braderie", t):
        return "market"
    for kw, cat in CATEGORY_MAP:
        if kw in t:
            return cat
    return "other"


def slug_date(url: str) -> str | None:
    """Extract the event ISO date from the URL slug (fallback)."""
    m = re.search(r"-(\d{4})-(\d{2})-(\d{2})/?$", url.rstrip("/"))
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        try:
            return date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            return None
    return None


def fetch_event_urls(client: httpx.Client, max_pages: int = 5) -> list[str]:
    """Return unique event detail URLs from the paginated search RSS."""
    urls: list[str] = []
    seen: set[str] = set()

    pages = [RSS_URL] + [f"{BASE_URL}/page/{n}/{SEARCH}&feed=rss2" for n in range(2, max_pages + 1)]
    for feed_url in pages:
        try:
            resp = client.get(feed_url)
            resp.raise_for_status()
        except Exception as e:
            print(f"  feed fetch failed {feed_url}: {e}", file=sys.stderr)
            continue
        root = ElementTree.fromstring(resp.text)
        for link in root.iter("link"):
            href = (link.text or "").strip()
            if "/event/" in href and href not in seen:
                seen.add(href)
                urls.append(href)

    return urls


def fetch_event_detail(url: str, client: httpx.Client) -> dict:
    """Fetch a Unidivers event detail page and parse its schema.org Event JSON-LD."""
    try:
        resp = client.get(url, follow_redirects=True, timeout=30.0)
        resp.raise_for_status()
    except Exception:
        return {}

    if "json" not in resp.headers.get("content-type", "") and resp.text.startswith("<?xml"):
        # shouldn't happen
        return {}
    return _parse_jsonld(resp.text, url)


def _parse_jsonld(html: str, url: str) -> dict:
    detail: dict = {}
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue
        graph = data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in graph:
            if isinstance(item, dict) and item.get("@type") == "Event":
                name = (item.get("name") or "").strip()
                if not name:
                    continue
                detail["title"] = name

                sd = item.get("startDate") or ""
                if sd:
                    detail["start_date"] = sd[:10]
                ed = item.get("endDate") or ""
                if ed:
                    detail["end_date"] = ed[:10]

                desc = (item.get("description") or "").strip()
                if desc:
                    # The description is the raw event text; clean excess whitespace
                    detail["description"] = re.sub(r"\s+", " ", desc).strip()[:800]

                loc = item.get("location") or {}
                if isinstance(loc, dict):
                    venue = loc.get("name") or ""
                    if venue and venue.lower() not in ("chamonix-mont-blanc",):
                        detail["venue_name"] = venue
                    addr = loc.get("address") or {}
                    if isinstance(addr, dict):
                        street = addr.get("streetAddress") or ""
                        locality = addr.get("addressLocality") or ""
                        if street:
                            detail["address"] = f"{street}, {locality}".strip(", ")

                img = item.get("image") or ""
                if isinstance(img, str) and img.startswith("http"):
                    detail["image_url"] = img
                elif isinstance(img, dict):
                    u = img.get("url")
                    if u:
                        detail["image_url"] = u

                offers = item.get("offers") or {}
                if isinstance(offers, dict):
                    price = offers.get("price")
                    if price is not None and price != "0.00":
                        cur = offers.get("priceCurrency", "EUR")
                        detail["price"] = f"{price} {cur}".strip()

                detail["category"] = classify_category(name)
                return detail
    # No JSON-LD Event found — fall back to slug date + a bare title
    title = _guess_title(html, url)
    if title:
        detail["title"] = title
        detail["start_date"] = slug_date(url) or ""
    return detail


def _guess_title(html: str, url: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if m:
        t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        return t
    return ""


def normalize(raw: dict) -> Event:
    ev = Event(
        title=raw.get("title", ""),
        description=(raw.get("description") or "").strip(),
        start_date=raw.get("start_date", ""),
        end_date=raw.get("end_date"),
        time=raw.get("time"),
        commune=raw.get("commune", "Chamonix"),
        category=raw.get("category") or "other",
        source_id=SOURCE_ID,
        source_url=raw.get("source_url", ""),
        image_url=raw.get("image_url"),
        price=raw.get("price"),
        venue_name=raw.get("venue_name"),
        address=raw.get("address"),
        status="published",
    )
    # Namespace the event id by source so the same title+date from another
    # source (e.g. mairie, chamonix.com) doesn't collide on the globally
    # UNIQUE events.id column.
    ev.id = f"{SOURCE_ID}-{ev.id}"
    ev.confidence = compute_confidence(SOURCE_ID, ev.to_dict())
    return ev


def run(dry_run: bool = False, do_detail: bool = True, max_pages: int = 5,
        max_events: int = 200, horizon_days: int = 365) -> None:
    start = datetime.now(timezone.utc)
    today = date.today()
    print(f"Scraping Unidivers search: {RSS_URL}", file=sys.stdout)

    try:
        with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
            urls = fetch_event_urls(client, max_pages=max_pages)
            print(f"  Discovered {len(urls)} Chamonix event URLs", file=sys.stdout)

            raw_events = []
            for url in urls[:max_events]:
                if do_detail:
                    d = fetch_event_detail(url, client)
                else:
                    d = {"title": _guess_title_from_slug(url), "start_date": slug_date(url) or ""}
                if not d.get("title"):
                    continue
                d["source_url"] = url
                d.setdefault("start_date", slug_date(url) or "")
                d.setdefault("commune", "Chamonix")
                raw_events.append(d)

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
    # Filter: only events with a start_date, not too far in the future,
    # and dedupe by (title, start_date).
    events = [e for e in events if e.title and e.start_date]
    kept = []
    seen = set()
    for e in events:
        try:
            sd = date.fromisoformat(e.start_date[:10])
        except ValueError:
            continue
        if sd < today:
            continue
        if (sd - today).days > horizon_days:
            continue
        k = (e.title.lower(), e.start_date[:10])
        if k in seen:
            continue
        seen.add(k)
        kept.append(e)
    events = kept
    events.sort(key=lambda e: e.start_date or "")

    if dry_run:
        has_desc = sum(1 for e in events if e.description)
        has_img = sum(1 for e in events if e.image_url)
        has_venue = sum(1 for e in events if e.venue_name)
        print(f"\n  DRY RUN - {len(events)} events ({has_desc}d {has_img}i {has_venue}v)\n", file=sys.stdout)
        for ev in events[:60]:
            print(f"  {ev.start_date or '???'} | {ev.category:10s} | {ev.title[:52]:52s} "
                  f"| {'D' if ev.description else ''}{'I' if ev.image_url else ''}{'V' if ev.venue_name else ''}",
                  file=sys.stdout)
        return

    rows = [e.to_dict() for e in events]
    count = get_storage().upsert_events(SOURCE_ID, rows)
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\nExported {len(events)} events (upserted {count}) in {elapsed:.1f}s", file=sys.stdout)


def _guess_title_from_slug(url: str) -> str:
    slug = url.rstrip("/").split("/event/")[-1].split("/")[0]
    # strip trailing date tokens like -2026-08-17 and commune suffixes
    slug = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", slug)
    return slug.replace("-", " ").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Chamonix events from Unidivers")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-detail", action="store_true")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-events", type=int, default=200)
    parser.add_argument("--horizon-days", type=int, default=365)
    args = parser.parse_args()
    run(dry_run=args.dry_run, do_detail=not args.no_detail, max_pages=args.max_pages,
        max_events=args.max_events, horizon_days=args.horizon_days)


if __name__ == "__main__":
    main()
