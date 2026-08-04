#!/usr/bin/env python3
"""T55: Derive real venue_name + commune for events from their address.

Before this, venue_name was NULL for every event and commune was hardcoded to
"Chamonix" — so every detail page showed "Venue: Chamonix / Location: Chamonix"
even for events in Vallorcine (74660), Les Houches (74310), Argentière (74400).

The address field already carries the real data, e.g.:
  "Patinoire du centre sportif Richard Bozon 214, avenue de la plage 74400 Chamonix-Mont-Blanc"
  => venue "Patinoire du centre sportif Richard Bozon", commune "Chamonix-Mont-Blanc"
  "Place du village 74400 Argentière" => venue "Place du village", commune "Argentière"

Usage:
    python -m scripts.enrich_venue_commune            # write DB
    python -m scripts.enrich_venue_commune --dry-run  # preview only
"""
import re
import sys
from scripts.storage import get_storage

# Street keywords that mark the START of the street/address portion of a venue
# string (used to split "Venue Name 12 rue des X" -> "Venue Name").
STREET_KW = (
    "allée", "allee", "avenue", "av.", "rue", "route", "rte", "impasse",
    "chemin", "place", "cours", "boulevard", "montée", "montee", "promenade",
    "quai", "passage", "sentier",
)

# Known communes (reliable tokens in the address).
COMMUNE_TOKENS = (
    "Chamonix-Mont-Blanc", "Chamonix", "Argentière", "Argentiere",
    "Les Houches", "Vallorcine", "Servoz", "Le Tour", "Les Praz",
)

# Postcode-only fallback (only used when the postcode has no trailing text).
POSTCODE_COMMUNE = {
    "74310": "Les Houches",
    "74660": "Vallorcine",
    "74400": "Chamonix",
}

# Special-case addresses that resolve to a known venue name.
ADDR_VENUE_OVERRIDES = {
    "22, cours bartavel": "Le Vox",
}


def _norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def derive_commune(addr):
    """Return a commune string from the address, or None if uncertain."""
    if not addr:
        return None
    addr = _norm(addr)
    codes = list(re.finditer(r"\b\d{5}\b", addr))
    if codes:
        code = codes[-1]
        trailing = addr[code.end():].strip(" ,-;")
        trailing = _norm(trailing)
        if trailing:
            # Normalise known commune spellings.
            for tok in ("Chamonix-Mont-Blanc", "Argentière", "Argentiere",
                        "Les Houches", "Vallorcine", "Servoz", "Chamonix"):
                if tok.lower() == trailing.lower():
                    return "Chamonix-Mont-Blanc" if tok == "Chamonix-Mont-Blanc" else tok
            # Unrecognised trailing text — use the postcode mapping if any.
            return POSTCODE_COMMUNE.get(code.group(0))
        return POSTCODE_COMMUNE.get(code.group(0))
    # No postcode — match known commune tokens in the text.
    for tok in COMMUNE_TOKENS:
        if re.search(r"\b" + re.escape(tok) + r"\b", addr, re.IGNORECASE):
            return tok
    return None


def derive_venue(addr):
    """Return a short venue name from the address, or '' if none."""
    if not addr:
        return ""
    al = addr.lower()
    # Explicit override (e.g. cinema address).
    for key, val in ADDR_VENUE_OVERRIDES.items():
        if key in al:
            return val
    addr = _norm(addr)
    # Cut everything from the postcode onwards.
    m = re.search(r"\b\d{5}\b", addr)
    head = addr[:m.start()].strip() if m else addr
    # Cut at the first "number + street keyword" -> leaves the venue name.
    kw_alt = "|".join(re.escape(k) for k in STREET_KW)
    m2 = re.search(r"\b\d{1,4}\b\s*,?\s*(" + kw_alt + r")\b", head, re.IGNORECASE)
    if m2:
        head = head[:m2.start()]
    head = _norm(head)
    # Strip trailing junk (commas, dashes, "et"), keep sensible length.
    head = re.sub(r"[\s,;:–—-]+$", "", head).strip()
    if not head or len(head) > 60:
        return head[:60].rstrip(" ,-") if head else ""
    return head


def main():
    dry = "--dry-run" in sys.argv
    storage = get_storage()
    events = storage.get_events()
    changed_venue = changed_commune = 0
    for e in events:
        eid = e["id"]
        addr = e.get("address") or ""
        updates = []
        # Venue
        if not (e.get("venue_name") or "").strip():
            v = derive_venue(addr)
            if v and v != (e.get("venue_name") or ""):
                updates.append(("venue_name", v))
        # Commune (only upgrade when we have a confident non-default value)
        cur = e.get("commune") or ""
        c = derive_commune(addr)
        if c and c and c != cur:
            updates.append(("commune", c))
        if updates:
            changed_venue += any(k == "venue_name" for k, _ in updates)
            changed_commune += any(k == "commune" for k, _ in updates)
            if dry:
                print(f"  {eid}\n     addr={addr!r}\n     -> {dict(updates)}")
            else:
                set_clause = ", ".join(f"{k} = ?" for k, _ in updates)
                vals = [v for _, v in updates] + [eid]
                with storage.conn:
                    storage.conn.execute(
                        f"UPDATE events SET {set_clause} WHERE id = ?", vals
                    )
    print(f"{'DRY RUN — ' if dry else ''}venue changes: {changed_venue}, commune changes: {changed_commune} "
          f"across {len(events)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
