"""T18: apply curated venue data from data/venues.json to SQLite.

Usage
-----
  python -m scripts.curate_venues [--dry-run]

Reads venues.json (now carrying curated latitude/longitude/postal_code/
categories/geocode_source fields) and UPSERTs into the venues table via
Storage.upsert_venue_curation().

Idempotent: re-running with the same input is a no-op (the UPDATE returns
rowcount=0 because the data already matches).

Why a separate script from update_venues_json.py?
  - update_venues_json.py is a one-shot seed enricher (T16 → JSON).
  - curate_venues.py is the operator's "apply curated JSON to DB" tool.
  - The two are independent: an operator can edit venues.json by hand,
    then run curate_venues.py to push changes. The reverse — write JSON
    from current SQLite — isn't supported because SQLite has its own
    provenance (T16 result, manual update, etc.) that doesn't belong in
    a hand-editable seed file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from scripts.storage import get_storage  # noqa: E402

VENUES_PATH = Path(__file__).resolve().parent.parent / "data" / "venues.json"


def _slug(s: str) -> str:
    """Same slug logic as scripts/storage.py:_slug."""
    import re

    s = (s or "").lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-") or "unnamed"


def main() -> int:
    p = argparse.ArgumentParser(
        description="Apply curated venues.json fields to SQLite (T18)."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change without writing",
    )
    args = p.parse_args()

    venues = json.loads(VENUES_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(venues)} venues from {VENUES_PATH}")

    s = get_storage()
    updated = 0
    skipped = 0
    needs_manual = 0

    for v in venues:
        vid = _slug(v.get("name", ""))
        payload = {
            "id": vid,
            "latitude": v.get("latitude"),
            "longitude": v.get("longitude"),
            "postal_code": v.get("postal_code"),
            "categories": v.get("categories"),
            "address": v.get("address"),
        }
        # Don't write coords for venues that need manual review
        if v.get("geocode_source") == "needs_manual_review":
            payload.pop("latitude", None)
            payload.pop("longitude", None)
            needs_manual += 1

        if args.dry_run:
            print(f"  would update {vid}: "
                  f"lat={payload.get('latitude')}, "
                  f"lng={payload.get('longitude')}, "
                  f"postal={payload.get('postal_code')}, "
                  f"cats={payload.get('categories')}")
            continue

        if s.upsert_venue_curation(payload):
            updated += 1
        else:
            skipped += 1

    if args.dry_run:
        print()
        print(f"(dry-run complete: {len(venues)} venues would be applied)")
    else:
        print()
        print(f"Done. updated={updated}  skipped={skipped}  needs_manual={needs_manual}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
