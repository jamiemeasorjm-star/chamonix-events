"""T16: Geocode venues via OpenStreetMap Nominatim.

Usage
-----
  python -m scripts.geocode_venues [--limit N] [--dry-run] [--force]

Geocodes venues that don't have lat/lng using the venue's address or name
plus the commune ("Chamonix"). Uses OpenStreetMap Nominatim — no API key
required, but rate-limited to ~1 req/sec per Nominatim ToS
(https://operations.osmfoundation.org/policies/nominatim/).

Idempotent: re-running skips venues that already have non-null,
non-zero coordinates. Use --force to re-geocode everything.

Examples
--------
  # Test the first 3 venues without writing to the DB
  python -m scripts.geocode_venues --limit 3 --dry-run

  # Geocode the next 5 venues (writes to DB)
  python -m scripts.geocode_venues --limit 5

  # Geocode everything (writes to DB; ~30s for 26 venues)
  python -m scripts.geocode_venues
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from scripts.storage import get_storage  # noqa: E402

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim ToS: User-Agent must identify the application and include a
# contact. Production should swap the URL for a real contact page.
USER_AGENT = "ChamonixEvents/1.0 (https://github.com/example/chamonix-events)"
# Slightly above 1.0s to stay safely under Nominatim's 1 req/sec cap.
REQUEST_DELAY_S = 1.1
DEFAULT_TIMEOUT_S = 10


def _nominatim_search(query: str, timeout: int = DEFAULT_TIMEOUT_S) -> tuple[float, float] | None:
    """Call Nominatim. Returns (lat, lng) or None if not found.

    Raises urllib errors on network failure. JSON/Key/Value errors are
    caught by the caller and turned into a per-venue warning.
    """
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 0,
        }
    )
    url = f"{NOMINATIM_URL}?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data:
        return None
    first = data[0]
    return float(first["lat"]), float(first["lon"])


def geocode_venue(venue: dict) -> tuple[float, float] | None:
    """Geocode a single venue. Returns (lat, lng) or None.

    Tries address first (more precise), then name + commune.
    """
    name = venue.get("name") or ""
    commune = venue.get("commune") or "Chamonix"
    address = venue.get("address")

    if address:
        query = f"{address}, {commune}, France"
    elif name:
        query = f"{name}, {commune}, France"
    else:
        return None

    try:
        return _nominatim_search(query)
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"  WARN: Nominatim error for {name!r}: {e}", file=sys.stderr)
        return None


def main() -> int:
    p = argparse.ArgumentParser(
        description="Geocode venues via OpenStreetMap Nominatim (T16)."
    )
    p.add_argument(
        "--limit", type=int, default=None, help="max venues to geocode this run"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="don't write to DB (still hits Nominatim)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="re-geocode even if coords already exist",
    )
    args = p.parse_args()

    s = get_storage()
    venues = s.get_venues()

    if args.force:
        targets = venues
        print(f"--force: re-geocoding all {len(targets)} venues")
    else:
        targets = [
            v
            for v in venues
            if v.get("latitude") is None
            or v.get("longitude") is None
            or v.get("latitude") == 0
            or v.get("longitude") == 0
        ]
        print(f"Pending geocoding: {len(targets)} of {len(venues)} venues")

    if args.limit:
        targets = targets[: args.limit]
        print(f"--limit: processing first {len(targets)} this run")

    if not targets:
        print("Nothing to do.")
        return 0

    if args.dry_run:
        print("(dry-run: no DB writes)")
    print()

    success = 0
    failed = 0
    for i, v in enumerate(targets):
        vid = v.get("id", "?")
        name = v.get("name") or vid
        coords = geocode_venue(v)
        if coords is None:
            print(f"  [{i+1}/{len(targets)}] {name}: NO RESULT")
            failed += 1
        else:
            lat, lng = coords
            print(f"  [{i+1}/{len(targets)}] {name}: {lat:.5f}, {lng:.5f}")
            if not args.dry_run:
                s.update_venue_coords(vid, lat, lng)
            success += 1
        # Rate limit — skip the sleep after the last iteration
        if i < len(targets) - 1:
            time.sleep(REQUEST_DELAY_S)

    print()
    mode = "(dry-run) " if args.dry_run else ""
    print(f"{mode}Done. success={success}  failed={failed}  total={len(targets)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
