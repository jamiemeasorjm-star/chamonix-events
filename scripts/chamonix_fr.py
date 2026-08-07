"""Scrape the Mairie de Chamonix agenda (chamonix.fr) for events.

Source: official mairie/commune agenda. Broadest coverage of the valley —
festivals, guided visits, conferences, exhibitions, cinema projections,
association events, sport (hockey demos), family ateliers.

The agenda listing pages are fully server-rendered (works with plain httpx +
BeautifulSoup, no browser needed). Each event card is an <a href="/agenda/<slug>/">
inside a container whose text is "<date> <category> <title>".

Registered as source_id `chamonix_fr` (trust high).
Follows the same conventions as chamonix_net.py (compute_confidence + upsert).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from scripts.models import Event
from scripts.storage import get_storage
from scripts.sources import get_source
from scripts.scoring import compute_confidence

BASE_URL = "https://www.chamonix.fr"
AGENDA_URL = f"{BASE_URL}/actualites-agenda/agenda/"
SOURCE_ID = "chamonix_fr"
_source = get_source(SOURCE_ID)
CONFIDENCE = _source.confidence_baseline() if _source else 1.0

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# French month -> 1-12 (lowercased, no accents variants)
MONTHS = {
    "jan": 1, "janv": 1, "janvier": 1,
    "fev": 2, "fevr": 2, "fevrier": 2, "février": 2,
    "mar": 3, "mars": 3,
    "avr": 4, "avril": 4,
    "mai": 5,
    "juin": 6, "jun": 6,
    "juil": 7, "juillet": 7, "jul": 7,
    "aout": 8, "août": 8, "ao": 8, "aug": 8,
    "sep": 9, "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10,
    "nov": 11, "novembre": 11,
    "dec": 12, "décembre": 12, "decembre": 12,
}


def _month_num(name: str) -> int | None:
    return MONTHS.get(name.strip().lower().rstrip("."))


def _date_to_iso(day: int, month: int, today: date | None = None) -> str:
    """Build ISO date from day+month, choosing a sensible year.

    Events near today. Use current year; if the result is more than ~3 months
    in the past (e.g. a Dec event seen in Jan), roll forward to next year so we
    never publish stale listings.
    """
    today = today or date.today()
    year = today.year
    dt = date(year, month, day)
    # Allow small lookback for multi-day events already started; if the date is
    # clearly in the past (more than 90 days ago), assume next year's edition.
    if (today - dt).days > 90:
        try:
            dt = date(year + 1, month, day)
        except ValueError:
            pass
    return dt.strftime("%Y-%m-%d")


DATE_SINGLE = re.compile(r"Le\s+(\d{1,2})\s+(\S+)", re.I)
DATE_RANGE = re.compile(r"Du\s+(\d{1,2})\s+(\S+)\s+(\d{1,2})\s+(\S+)", re.I)


def parse_card_date(text: str, today: date | None = None) -> tuple[str, str | None]:
    """Return (start_date_iso, end_date_iso) from an agenda card's text."""
    today = today or date.today()

    m = DATE_RANGE.search(text)
    if m:
        d1, mo1, d2, mo2 = m.group(1), m.group(2), m.group(3), m.group(4)
        m1, m2 = _month_num(mo1), _month_num(mo2)
        if m1 and m2:
            s = _date_to_iso(int(d1), m1, today)
            # End month may be a different (later) month/year
            e = _date_to_iso(int(d2), m2, today)
            # if end appears before start, roll end to next year
            if e < s:
                y = date.fromisoformat(s).year + 1
                e = date(y, m2, int(d2)).isoformat()
            return s, e

    m = DATE_SINGLE.search(text)
    if m:
        d1, mo1 = m.group(1), m.group(2)
        m1 = _month_num(mo1)
        if m1:
            s = _date_to_iso(int(d1), m1, today)
            return s, s

    return "", None


# French category label -> canonical event category
CATEGORY_MAP = [
    ("concert", "concert"),
    ("festival", "concert"),
    ("musique", "concert"),
    ("cinema", "exhibition"),  # projections -> exhibition-ish
    ("projection", "exhibition"),
    ("theatre", "theatre"),
    ("spectacle", "theatre"),
    ("visite guidee", "exhibition"),
    ("visite guidée", "exhibition"),
    ("exposition", "exhibition"),
    ("conférence", "other"),
    ("conference", "other"),
    ("debat", "other"),
    ("rencontre", "other"),
    ("competition sportive", "sport"),
    ("compétition sportive", "sport"),
    ("demonstration", "sport"),
    ("démonstration", "sport"),
    ("marche", "sport"),
    ("randonnee", "sport"),
    ("randonnée", "sport"),
    ("sport", "sport"),
    ("marché", "market"),
    ("marche", "market"),  # "Marché" (market) vs "marche" (walk) - handled below
    ("foire", "market"),
    ("brocante", "market"),
    ("vide grenier", "market"),
    ("vide-grenier", "market"),
    ("dessin", "family"),
    ("enquête", "family"),
    ("enquete", "family"),
    ("fresque", "family"),
    ("zumba", "sport"),
    ("guinguette", "concert"),
    ("enfant", "family"),
    ("famille", "family"),
    ("atelier", "family"),
    ("animation", "family"),
    ("jeune public", "family"),
    ("match", "sport"),
    ("repas organise", "other"),
]


def classify_category(text: str) -> str:
    t = text.lower()
    # Market takes precedence over "Marche" (walk) when it's a market/fair
    if re.search(r"march[ée]|foire|brocante", t):
        return "market"
    for kw, cat in CATEGORY_MAP:
        if kw in t:
            return cat
    return "other"


def extract_agenda_events(html: str) -> list[dict]:
    """Parse agenda page cards into raw event dicts (title, dates, category, url)."""
    soup = BeautifulSoup(html, "html.parser")
    events: list[dict] = []
    today = date.today()

    for a in soup.select('a[href*="/agenda/"]'):
        href = a.get("href", "").strip()
        # Skip the hub itself and filter links
        if "/actualites-agenda/" in href or href.rstrip("/").endswith("/agenda"):
            continue
        if not href.startswith("https://www.chamonix.fr/agenda/"):
            continue
        title = a.get_text(" ", strip=True).strip()
        if not title:
            continue

        # Find the surrounding card container for date + category context.
        # The card is an <article class="card ..."> — narrow to a single card so
        # we don't pull sibling cards' category labels into the context.
        parent = a.find_parent("article", class_="card")
        if parent is None:
            parent = a.find_parent(["li"])
        context = parent.get_text(" ", strip=True) if parent else title
        start, end = parse_card_date(context, today)
        if not start:
            continue

        # Classify from the TITLE first (most specific); fall back to the card
        # context (theme label) only when the title gives no signal — a theme
        # like "Démonstration" shouldn't override a title like "Atelier/enfant".
        category = classify_category(title)
        if category == "other":
            category = classify_category(context)
        events.append({
            "title": title,
            "start_date": start,
            "end_date": end,
            "category": category,
            "source_url": href,
            "commune": "Chamonix",
        })
    return events


def fetch_detail(url: str, client: httpx.Client) -> dict:
    """Fetch a mairie event detail page for description/image/venue/price."""
    detail: dict = {}
    try:
        resp = client.get(url, follow_redirects=True, timeout=30.0)
        resp.raise_for_status()
    except Exception:
        return detail

    soup = BeautifulSoup(resp.text, "html.parser")

    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        detail["image_url"] = og["content"]

    # Description: main content text, trimmed
    main = soup.select_one("main") or soup.select_one("article") or soup
    text = main.get_text("\n", strip=True) if main else ""
    # Collapse repeated whitespace/newlines
    text = re.sub(r"\n{2,}", "\n", text).strip()
    # Drop boilerplate nav lines at the start
    description = text
    for kw in ["Aller au contenu", "Menu démarches", "Recherche", "Démarches", "EN / FR",
               "Paramètres d'accessibilité", "Réinitialiser", "Valider"]:
        if kw in description:
            description = description.split(kw)[0]
    if len(description) > 600:
        description = description[:600].rsplit(".", 1)[0] + "."
    if description:
        detail["description"] = description

    # Price
    m = re.search(r"Tarifs?\s+(.{0,120})", text)
    if m:
        detail["price"] = m.group(1).strip()[:120]

    return detail


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
    # source (e.g. Unidivers, chamonix.com) doesn't collide on the globally
    # UNIQUE events.id column.
    ev.id = f"{SOURCE_ID}-{ev.id}"
    ev.confidence = compute_confidence(SOURCE_ID, ev.to_dict())
    return ev


def run(dry_run: bool = False, do_detail: bool = True, max_pages: int = 8) -> None:
    start = datetime.now(timezone.utc)
    print(f"Scraping {AGENDA_URL}", file=sys.stdout)

    all_cards: list[dict] = []
    try:
        with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
            # Page 1 + subsequent pages (agenda is paginated: /page/N/)
            pages = [AGENDA_URL] + [f"{AGENDA_URL}page/{n}/" for n in range(2, max_pages + 1)]
            for page_url in pages:
                try:
                    resp = client.get(page_url)
                    resp.raise_for_status()
                except Exception as e:
                    print(f"  page fetch failed {page_url}: {e}", file=sys.stderr)
                    continue
                cards = extract_agenda_events(resp.text)
                print(f"  {page_url} -> {len(cards)} events", file=sys.stdout)
                all_cards.extend(cards)
                # stop paginating if page empty
                if not cards:
                    break

            # De-duplicate by (title, start_date) across pages
            seen = set()
            deduped = []
            for c in all_cards:
                k = (c["title"].lower(), c["start_date"])
                if k in seen:
                    continue
                seen.add(k)
                deduped.append(c)

            raw_events = deduped
            if do_detail:
                enriched = []
                for ev in raw_events:
                    d = fetch_detail(ev["source_url"], client)
                    ev.update(d)
                    enriched.append(ev)
                raw_events = enriched
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
    # drop events with no title/date (normalize produced empty)
    events = [e for e in events if e.title and e.start_date]
    events.sort(key=lambda e: e.start_date or "")

    if dry_run:
        has_desc = sum(1 for e in events if e.description)
        has_img = sum(1 for e in events if e.image_url)
        print(f"\n  DRY RUN - {len(events)} events ({has_desc}d {has_img}i)\n", file=sys.stdout)
        for ev in events:
            print(f"  {ev.start_date or '???'} | {ev.category:12s} | {ev.title[:55]:55s} "
                  f"| {'D' if ev.description else ' no-desc'}{'I' if ev.image_url else ''}",
                  file=sys.stdout)
        return

    rows = [e.to_dict() for e in events]
    count = get_storage().upsert_events(SOURCE_ID, rows)
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\nExported {len(events)} events (upserted {count}) in {elapsed:.1f}s", file=sys.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape mairie de Chamonix agenda (chamonix.fr)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-detail", action="store_true", help="Skip detail page enrichment")
    parser.add_argument("--max-pages", type=int, default=8)
    args = parser.parse_args()
    run(dry_run=args.dry_run, do_detail=not args.no_detail, max_pages=args.max_pages)


if __name__ == "__main__":
    main()
