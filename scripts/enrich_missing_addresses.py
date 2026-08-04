#!/usr/bin/env python3
"""T55: Fetch addresses for events that are still missing venue/address.

Uses the same parse logic as the live scrapers:
  - chamonix.net : venue = .event-venue, address = .event-address
  - chamonix.com : address = div.onglet-content[data-onglet=localisation] > .adresse

Derives venue_name/commune from the address via scripts.enrich_venue_commune.

Usage:
    python -m scripts.enrich_missing_addresses --dry-run
    python -m scripts.enrich_missing_addresses          # write DB
"""
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from bs4 import BeautifulSoup

from scripts.storage import get_storage
from scripts.enrich_venue_commune import derive_commune, derive_venue

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def fetch(url, timeout=20):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_address(source_id, html):
    soup = BeautifulSoup(html, "html.parser")
    if source_id == "chamonix_net":
        venue_el = soup.select_one(".event-venue")
        venue = venue_el.get_text(strip=True)[:100] if venue_el else ""
        addr_el = soup.select_one(".event-address")
        address = addr_el.get_text(strip=True)[:200] if addr_el else ""
        return venue, address
    if source_id == "chamonix_com":
        loc = soup.find("div", class_="onglet-content", attrs={"data-onglet": "localisation"})
        if loc:
            addr = loc.find("div", class_="adresse")
            if addr:
                address = " ".join(addr.stripped_strings)
                return "", address
        return "", ""
    return "", ""


def main():
    dry = "--dry-run" in sys.argv
    storage = get_storage()
    events = storage.get_events()
    targets = [e for e in events
               if not (e.get("address") or "").strip()]
    print(f"{len(targets)} events missing an address")
    changes = 0
    for e in targets:
        url = e.get("source_url") or ""
        if not url:
            print(f"  SKIP {e['id']}: no source_url")
            continue
        try:
            html = fetch(url)
            sc_venue, address = parse_address(e.get("source_id"), html)
        except (HTTPError, URLError, TimeoutError, OSError) as ex:
            print(f"  FETCH-FAIL {e['id']} ({url})\n      {ex}")
            continue
        venue = sc_venue or derive_venue(address)
        commune = derive_commune(address)
        print(f"  {e['id']}\n     url={url}\n     venue={venue!r} commune={commune!r} address={address!r}")
        if dry:
            continue
        if not address:
            continue
        updates = {"address": address}
        if venue:
            updates["venue_name"] = venue
        if commune:
            updates["commune"] = commune
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [e["id"]]
        with storage.conn:
            storage.conn.execute(f"UPDATE events SET {cols} WHERE id = ?", vals)
        changes += 1
    print(f"{'DRY RUN — ' if dry else ''}updated {changes} events")


if __name__ == "__main__":
    sys.exit(main())
