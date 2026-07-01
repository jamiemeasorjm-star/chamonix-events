"""T18: one-shot script to update data/venues.json with curated fields.

Run once. Idempotent.

Reads:
  - data/venues.json (existing 26-venue seed)
  - SQLite DB (T16 + refined Nominatim coords from geocode_venues.py)

Writes:
  - data/venues.json (adds latitude, longitude, postal_code, categories,
    geocode_source to every entry)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from scripts.storage import get_storage  # noqa: E402
from scripts.models import write_atomic_json  # noqa: E402

VENUES_PATH = Path(__file__).resolve().parent.parent / "data" / "venues.json"


def _slug(s: str) -> str:
    """Same slug logic as scripts/storage.py:_slug.

    Inlined to avoid pulling storage's private fn into this script.
    """
    import re

    s = (s or "").lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-") or "unnamed"

# Hand-curated coords that are MORE PRECISE than what T16 found via
# Nominatim (street centroids, not individual bar locations). Each entry
# records the source so we can audit later.
REFINED_COORDS = {
    "bar-dup":       (45.92474, 6.87042, "nominatim_name_first"),
    "bar-du-moulin": (45.92436, 6.87049, "nominatim_name_first"),
    "mix-bar":       (45.92440, 6.87057, "nominatim_name_first"),
    "french-blvd":   (45.92544, 6.87095, "nominatim_name_first"),
    # Also refined from the multi-query test (found in T18 setup):
    "le-solerey-brewpub": (45.89252, 6.80024, "nominatim_address_full"),
    "cafe-de-la-gare":    (45.90677, 6.83925, "nominatim_name_commune"),
    "le-vox":             (45.92316, 6.86895, "nominatim_alias_cinema"),
}

POSTAL_CODE = "74400"  # Chamonix-Mont-Blanc

# Venues that need manual coord entry (Nominatim has no in-Chamonix result).
NEEDS_MANUAL = {"amnesia", "le-garage", "moon-tines"}


def derive_categories(v: dict) -> list[str]:
    """T18: derive categories from existing boolean fields + name."""
    cats = ["venue"]
    if v.get("has_live_music"):
        cats.append("live_music")
    if v.get("has_event_page"):
        cats.append("events")
    name = (v.get("name") or "").lower()
    if "vox" in name:
        cats.append("cinema")
    # Most of these are nightlife venues by inspection
    if any(w in name for w in ("bar ", "pub", "brew", "club", "garage", "amnesia")):
        cats.append("bar")
    if "restaurant" in name or "cafe" in name or "maison" in name:
        cats.append("restaurant")
    return sorted(set(cats))


def main() -> int:
    venues = json.loads(VENUES_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(venues)} venues from {VENUES_PATH}")

    # Pull T16's coords from SQLite
    s = get_storage()
    db_venues = {row["id"]: dict(row) for row in s.conn.execute(
        "SELECT id, latitude, longitude FROM venues"
    ).fetchall()}
    have_coords = sum(1 for v in db_venues.values()
                      if v["latitude"] is not None and v["latitude"] != 0)
    print(f"SQLite has {have_coords}/{len(db_venues)} venues with coords (T16 result)")

    updated = 0
    for v in venues:
        # venues.json doesn't carry an explicit id — it's slugified from name
        # by scripts/storage.py on insert. Same rule here.
        vid = _slug(v.get("name", ""))
        v["id"] = vid  # now persisted for downstream tools
        # Start with T16 coords (if any)
        if vid in db_venues and db_venues[vid]["latitude"]:
            v["latitude"] = db_venues[vid]["latitude"]
            v["longitude"] = db_venues[vid]["longitude"]
            v["geocode_source"] = "nominatim_t16"
        # Override with refined coords
        if vid in REFINED_COORDS:
            lat, lng, src = REFINED_COORDS[vid]
            v["latitude"] = lat
            v["longitude"] = lng
            v["geocode_source"] = src
        # Mark manual-review venues
        if vid in NEEDS_MANUAL:
            v.pop("latitude", None)
            v.pop("longitude", None)
            v["geocode_source"] = "needs_manual_review"
        # Postal code + categories for everyone
        v["postal_code"] = POSTAL_CODE
        v["categories"] = derive_categories(v)
        updated += 1

    # Atomic write
    write_atomic_json(str(VENUES_PATH), venues)
    print(f"Wrote {updated} venues back to {VENUES_PATH}")
    print()
    # Summary
    with_coords = sum(1 for v in venues if v.get("latitude"))
    needs_manual = sum(1 for v in venues if v.get("geocode_source") == "needs_manual_review")
    print(f"Summary:")
    print(f"  total venues:    {len(venues)}")
    print(f"  with coords:     {with_coords}")
    print(f"  need manual:     {needs_manual}")
    print(f"  postal codes:    {sum(1 for v in venues if v.get('postal_code'))}")
    print(f"  with categories: {sum(1 for v in venues if v.get('categories'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
