#!/usr/bin/env python3
"""wf-based chamonix.com event-detail scraper (web-foundation migration, slice 1).

Fixes the empty-description bug in the old httpx-only chamonix_com_detail.py:
chamonix.com event pages are JS-heavy, so a plain httpx fetch historically
yields no description. This module uses the web-foundation (wf) toolkit:
    - fast path:  scripts.web_foundation.extract_url (server-rendered content)
    - fallback:   BrowserSession (Playwright JS render) when the fast path
                  yields no/empty description
Description/title come from the wf Extraction (markdown field). Structured
fields (dates, price, address, commune) are parsed from the raw HTML DOM.

READ-ONLY module: it never writes to storage / the DB. Use --dry-run to print
the parsed event dicts as JSON.

Run (must use the web-foundation venv, wf deps live only there):
    export PYTHONPATH=/docker/hermes-agent-2bpx/data/chamonix-events
    /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python -m \\
        scripts.wf_chamonix_com --url "https://www.chamonix.com/agenda/.../slug" --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass

from bs4 import BeautifulSoup

from scripts.web_foundation import extract_url
from scripts.web_foundation.browser import BrowserSession

SOURCE_ID = "chamonix_com"
MIN_DESCRIPTION_LEN = 120

MONTHS_FR = {
    "janvier": "01", "février": "02", "mars": "03", "avril": "04",
    "mai": "05", "juin": "06", "juillet": "07", "août": "08",
    "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12",
}

COMMUNE_MAP = {
    "chamonix-mont-blanc": "Chamonix",
    "argentière": "Argentiere",
    "les houches": "Les Houches",
    "servoz": "Servoz",
    "vallorcine": "Vallorcine",
}

CATEGORY_KEYWORDS: list[tuple[list[str], str]] = [
    (["concert", "chorale", "chœur", "choeur", "musique", "orchestre", "dub"], "concert"),
    (["théâtre", "theatre", "spectacle"], "theatre"),
    (["sport", "marathon", "escalade", "ski", "randonnée", "vélo", "course",
      "hockey", "utmb", "trail"], "sport"),
    (["marché", "marche", "brocante", "vide grenier", "vide-grenier"], "market"),
    (["exposition", "photo", "peinture", "musée", "festival"], "exhibition"),
    (["soirée", "bar", "club"], "nightlife"),
    (["enfant", "famille", "jeune public", "jeu"], "family"),
]


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------

def strip_front_matter(markdown: str) -> str:
    """Remove a leading YAML front-matter block (--- ... ---) if present."""
    if not markdown or not markdown.startswith("---"):
        return markdown
    lines = markdown.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:])
    return markdown


def first_heading(markdown: str) -> str:
    """Return the first ATX heading (e.g. '# Title') from markdown, stripped."""
    if not markdown:
        return ""
    for line in markdown.splitlines():
        s = line.lstrip()
        if s.startswith("#"):
            return s.lstrip("#").strip()
    return ""


def extract_description(markdown: str) -> str:
    """Strip wf YAML front-matter and collapse whitespace to a clean description.

    This is the field that fixes the old empty-description bug.
    """
    body = strip_front_matter(markdown or "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if ln]
    text = "\n\n".join(lines).strip()
    return _strip_trailing_address(text)


def _strip_trailing_address(text: str) -> str:
    """Drop a trailing standalone French postal line like '74400 Chamonix-Mont-Blanc'."""
    paras = text.split("\n\n")
    if paras and re.fullmatch(r"\d{5}\s+[A-Za-zÀ-ÿ\-'\s]+", paras[-1].strip()):
        paras = paras[:-1]
    return "\n\n".join(paras).strip()


def detect_commune(text: str) -> str:
    """Map a French place name (case-insensitive) to a canonical commune."""
    return _detect_commune_strict(text) or "Chamonix"


def _detect_commune_strict(text: str) -> str:
    t = (text or "").lower()
    for key, val in COMMUNE_MAP.items():
        if key in t:
            return val
    return ""


def extract_address_line(text: str, default: str = "") -> str:
    """Find a French postal-code line like '74400 Chamonix-Mont-Blanc'."""
    m = re.search(r"\b\d{5}\s+[A-Za-zÀ-ÿ\-'\s]+", text or "")
    return m.group(0).strip() if m else default


def _prefix_before_postcode(text: str) -> str:
    """Return the part of a place string that precedes the first postal code."""
    m = re.search(r"\b\d{5}\b", text or "")
    return text[:m.start()].strip(" -") if m else ""


def parse_event_time(text: str) -> str:
    """Return the first 'HHh[MM]' / 'HH:MM' start time as 'HH:MM' (else '')."""
    m = re.search(r"\b(\d{1,2})h(\d{2})?\b|\b(\d{1,2}):(\d{2})\b", text or "")
    if not m:
        return ""
    if m.group(1) is not None:
        hour = int(m.group(1))
        minute = m.group(2) or "00"
    else:
        hour = int(m.group(3))
        minute = m.group(4)
    return f"{hour:02d}:{minute}"


def parse_french_dates(text: str) -> tuple[str, str]:
    """Parse French date text like 'Du mercredi 12 au dimanche 16 août 2026.'

    Returns (start_date, end_date) as ISO YYYY-MM-DD strings ('' when unknown).
    """
    text = text or ""

    # Du <dow> <sd> au <dow> <ed> <month> <year>      (same month/year)
    m = re.search(
        r"Du\s+\w+\s+(\d+)\s+au\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        sd, ed, month, year = m.group(1), m.group(2), m.group(3), m.group(4)
        mo = MONTHS_FR.get(month.lower())
        if mo:
            return f"{year}-{mo}-{int(sd):02d}", f"{year}-{mo}-{int(ed):02d}"

    # Du <dow> <sd> <m1> <y1> au <dow> <ed> <m2> <y2>
    m = re.search(
        r"Du\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})\s+au\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        sd, sm, sy = m.group(1), m.group(2), m.group(3)
        ed, em, ey = m.group(4), m.group(5), m.group(6)
        smn, emn = MONTHS_FR.get(sm.lower()), MONTHS_FR.get(em.lower())
        if smn and emn:
            return f"{sy}-{smn}-{int(sd):02d}", f"{ey}-{emn}-{int(ed):02d}"

    # Le <dow> <day> <month> <year>   (single day)
    m = re.search(
        r"Le\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        mo = MONTHS_FR.get(month.lower())
        if mo:
            iso = f"{year}-{mo}-{int(day):02d}"
            return iso, iso

    return "", ""


def classify_category(title: str, description: str = "") -> str:
    text = (title + " " + description).lower()
    for keywords, cat in CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return cat
    return "other"


# ---------------------------------------------------------------------------
# Structured-field parsing from raw HTML DOM
# ---------------------------------------------------------------------------

@dataclass
class RawPage:
    extraction: object        # wf Extraction
    html: str = ""            # raw HTML (browser-rendered when fallback used)

    @property
    def markdown(self) -> str:
        return (self.extraction.markdown or "") if self.extraction else ""


def parse_structured_html(html: str) -> dict:
    """Extract dates/price/address/commune from chamonix.com onglet(tab) DOM."""
    out: dict = {}
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")

    ville = soup.find("div", class_="ville")
    if ville:
        txt = ville.get_text(strip=True).replace("à ", "").strip()
        if txt:
            out["commune_raw"] = txt

    for onglet in ("presentation", "tarifs", "ouvertures", "localisation"):
        div = soup.find("div", class_="onglet-content", attrs={"data-onglet": onglet})
        if div:
            out[f"{onglet}_text"] = div.get_text(" ", strip=True)

    adiv = soup.find("div", class_="adresse")
    if adiv:
        addr = " ".join(adiv.stripped_strings)
        if addr:
            out["address"] = addr
    return out


def _fetch_html_fast(url: str) -> str:
    """Fetch raw HTML via wf's polite httpx fetch (best-effort)."""
    try:
        from scripts.web_foundation import fetch_html
        return fetch_html(url, timeout=25.0)
    except Exception:
        return ""


def _extract_fast(url: str) -> RawPage:
    ex = extract_url(url, engine="auto")
    html = _fetch_html_fast(url)
    return RawPage(extraction=ex, html=html)


def _extract_browser(url: str) -> RawPage:
    """JS-render fallback using BrowserSession (Playwright)."""
    with BrowserSession() as b:
        page = b.get(url, wait_ms=1500)
    return RawPage(extraction=page.extract(), html=page.html)


def extract_event(url: str, use_browser_fallback: bool = True) -> dict:
    """Extract one chamonix.com event page into the pipeline's Event fields."""
    raw = _extract_fast(url)
    used_browser = False
    desc = extract_description(raw.markdown)

    if use_browser_fallback and (raw.extraction.status != "ok" or len(desc) < MIN_DESCRIPTION_LEN):
        raw = _extract_browser(url)
        used_browser = True
        desc = extract_description(raw.markdown)

    md = raw.markdown
    ex = raw.extraction
    title = first_heading(md) or (ex.title or "")
    if " : " in title:
        title = title.split(" : ")[0].strip()

    struct = parse_structured_html(raw.html)
    date_text = struct.get("ouvertures_text", "") or md
    start_date, end_date = parse_french_dates(date_text)
    time = parse_event_time(struct.get("ouvertures_text", "") or md)

    addr_text = struct.get("address", "") or md
    address = struct.get("address") or extract_address_line(md) or None
    commune = (
        _detect_commune_strict(addr_text)
        or _detect_commune_strict(struct.get("commune_raw", ""))
        or "Chamonix"
    )

    venue_name = None
    if address:
        v = _prefix_before_postcode(address)
        if v:
            venue_name = v[:100]

    price = struct.get("tarifs_text") or None

    return {
        "title": title,
        "description": desc,
        "start_date": start_date,
        "end_date": end_date or None,
        "time": time or None,
        "venue_name": venue_name,
        "address": address,
        "category": classify_category(title, desc),
        "commune": commune,
        "source_url": url,
        "image_url": (ex.image or None),
        "price": price,
        "source_id": SOURCE_ID,
        "confidence": 1.0 if desc else 0.3,
        "used_browser_fallback": used_browser,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _collect_urls(args) -> list[str]:
    urls: list[str] = []
    urls.extend(args.url or [])
    if args.urls_file:
        with open(args.urls_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    return urls


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="wf-based chamonix.com detail scraper")
    ap.add_argument("--url", action="append", default=[], help="event URL (repeatable)")
    ap.add_argument("--urls-file", help="file with one URL per line")
    ap.add_argument("--dry-run", action="store_true", help="print parsed events as JSON, no writes")
    ap.add_argument("--no-browser", action="store_true", help="disable JS-render fallback")
    args = ap.parse_args(argv)

    urls = _collect_urls(args)
    if not urls:
        ap.error("provide at least one --url or --urls-file")

    events = []
    for u in urls:
        ev = extract_event(u, use_browser_fallback=not args.no_browser)
        if args.dry_run:
            print(json.dumps(ev, ensure_ascii=False, indent=2))
        else:
            print(f"{'OK ' if ev['description'] else 'FAIL'} {ev['title']} desc={len(ev['description'])}c")
        events.append(ev)

    if args.dry_run:
        print(f"\n# {len(events)} event(s) parsed (dry-run, no writes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
