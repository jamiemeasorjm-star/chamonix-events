#!/usr/bin/env python3
"""
Normalize + Merge Pipeline for Chamonix Events

Takes raw Facebook scraped data (from facebook_graph.py), normalises
to EVENTS format, deduplicates against existing events.json, merges,
and writes back events.json + venue data.

Usage:
    python3 normalize.py --input data/facebook_20260527_120000_raw.json
    python3 normalize.py --latest   # auto-pick newest raw file
"""

import json, sys, os, re, hashlib, argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
PROJECT_DIR = SCRIPT_DIR.parent
EVENTS_PATH = PROJECT_DIR / "events.json"

CATEGORY_MAP = {
    'concert': 'concert', 'music': 'concert', 'live music': 'concert',
    'dj': 'concert', 'party': 'concert', 'soirée': 'concert', 'soiree': 'concert',
    'nightlife': 'concert', 'club': 'concert',
    'cinema': 'Cinema', 'film': 'Cinema', 'movie': 'Cinema',
    'exhibition': 'exhibition', 'expo': 'exhibition', 'art': 'exhibition',
    'theatre': 'theatre', 'theater': 'theatre', 'show': 'theatre',
    'sport': 'sport', 'sports': 'sport', 'competition': 'sport',
    'market': 'market', 'marché': 'market', 'marche': 'market',
    'family': 'family', 'kids': 'family', 'enfant': 'family',
    'festival': 'concert',
}

SOURCE_PRIORITY = {
    'chamonix_com': 10,
    'allocine': 10,
    'fb_event': 30,
    'fb_post': 50,
}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def make_event_id(title: str, start_date: str) -> str:
    """Create a stable, human-readable event ID."""
    base = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40]
    date_part = start_date[:10] if start_date else 'nodate'
    return f"{date_part}-{base}"


def normalize_fb_event(raw: dict) -> Optional[dict]:
    """Convert a raw Facebook scraped event into the EVENTS format."""
    title = raw.get('title', '').strip()
    if not title or len(title) < 3:
        return None

    start_date = raw.get('start_date', '')[:10] if raw.get('start_date') else ''
    end_date = raw.get('end_date', '')[:10] if raw.get('end_date') else ''

    # Try to extract category from description if not set
    category = raw.get('category', 'other')
    if category == 'other' and raw.get('description'):
        desc_lower = raw['description'].lower()
        for keyword, mapped_cat in CATEGORY_MAP.items():
            if keyword in desc_lower and mapped_cat != 'other':
                category = mapped_cat
                break

    event_id = make_event_id(title, start_date)

    # Clean up description
    description = raw.get('description', '') or ''
    description = re.sub(r'\s+', ' ', description).strip()
    if len(description) > 3000:
        description = description[:3000] + '...'

    return {
        'id': event_id,
        'title': title,
        'description': description[:2000],
        'start_date': start_date,
        'end_date': end_date,
        'time': raw.get('time', ''),
        'category': category,
        'commune': raw.get('commune', 'Chamonix'),
        'source_id': f"fb_{raw.get('page_id', 'unknown')}",
        'source_url': raw.get('source_url', ''),
        'image_url': raw.get('image_url', ''),
        'venue': raw.get('venue', ''),
        'address': raw.get('address', ''),
        'status': 'published',
        'confidence': raw.get('confidence', 0.7),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }


def dedup_key(event: dict) -> str:
    """Generate a dedup key from title + start_date."""
    title = re.sub(r'[^a-z0-9]', '', (event.get('title', '') or '').lower())[:50]
    date = (event.get('start_date', '') or '')[:10]
    return f"{title}|{date}"


def load_existing(path: Path) -> list:
    """Load existing events from events.json. Returns [] if not found."""
    if not path.exists():
        log(f"No existing events.json at {path}")
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        log(f"Warning: events.json is not a list ({type(data).__name__})")
        return []
    except (json.JSONDecodeError, Exception) as e:
        log(f"Warning: Could not load existing events.json: {e}")
        return []


def find_latest_raw() -> Optional[Path]:
    """Find the most recent raw Facebook output file."""
    files = sorted(DATA_DIR.glob('facebook_*_raw.json'), reverse=True)
    return files[0] if files else None


def main():
    parser = argparse.ArgumentParser(description='Normalize and merge Facebook events')
    parser.add_argument('--input', '-i', type=str, help='Path to raw FB scraped data')
    parser.add_argument('--latest', '-l', action='store_true', help='Auto-pick newest raw file')
    parser.add_argument('--dry-run', '-n', action='store_true', help='Preview changes without writing')
    args = parser.parse_args()

    # Determine input file
    if args.input:
        input_path = Path(args.input)
    elif args.latest:
        input_path = find_latest_raw()
        if not input_path:
            log("ERROR: No raw Facebook data files found in data/")
            sys.exit(1)
        log(f"Auto-picked: {input_path.name}")
    else:
        # If running as part of run.sh — try auto
        input_path = find_latest_raw()
        if input_path:
            log(f"Auto-picked: {input_path.name}")
        else:
            log("ERROR: No input specified and no raw files found.")
            log("Usage: python3 normalize.py --input <file> or --latest")
            sys.exit(1)

    # Load raw data
    try:
        with open(input_path) as f:
            raw_data = json.load(f)
    except Exception as e:
        log(f"ERROR: Could not load {input_path}: {e}")
        sys.exit(1)

    raw_events = raw_data.get('events', [])
    if not raw_events:
        log("No events in raw data — nothing to normalize.")
        return

    log(f"Loaded {len(raw_events)} raw events from {input_path.name}")

    # Normalize
    normalized = []
    for raw in raw_events:
        ev = normalize_fb_event(raw)
        if ev:
            normalized.append(ev)

    log(f"Normalized: {len(normalized)} valid events")

    # Load existing events
    existing = load_existing(EVENTS_PATH)
    log(f"Existing events: {len(existing)}")

    # Dedup: build index of existing keys
    existing_keys = {}
    for i, ev in enumerate(existing):
        key = dedup_key(ev)
        existing_keys[key] = i

    new_events = []
    duplicates = 0
    updated = 0

    for ev in normalized:
        key = dedup_key(ev)
        if key in existing_keys:
            idx = existing_keys[key]
            existing_source = existing[idx].get('source_id', '')
            new_source = ev.get('source_id', '')

            # Get source priority (lower = higher priority)
            existing_priority = SOURCE_PRIORITY.get(existing_source, 50)
            new_priority = SOURCE_PRIORITY.get(new_source, 50)

            if new_priority < existing_priority:
                # New event is from a more reliable source — update
                # Preserve original created_at
                ev['created_at'] = existing[idx].get('created_at', ev['created_at'])
                existing[idx] = ev
                updated += 1
            elif new_priority == existing_priority and ev.get('confidence', 0) > existing[idx].get('confidence', 0):
                existing[idx] = ev
                updated += 1
            else:
                duplicates += 1
        else:
            new_events.append(ev)

    log(f"Results: {len(new_events)} new, {updated} updated, {duplicates} duplicates skipped")

    # Merge
    merged = existing + new_events

    # Sort by start_date ascending, then title
    merged.sort(key=lambda e: (e.get('start_date', '') or '', e.get('title', '') or ''))

    # Build venue data from merged events
    venue_map = {}
    for ev in merged:
        vname = ev.get('venue', '') or guess_venue(ev)
        if not vname:
            continue
        if vname not in venue_map:
            venue_map[vname] = {
                'name': vname, 'key': vname,
                'type': guess_type(ev.get('category', 'other')),
                'location': 'Chamonix',
                'desc': '', 'count': 0,
                'categories': set(), 'indices': [],
            }
        venue_map[vname]['count'] += 1
        venue_map[vname]['categories'].add(ev.get('category', 'other'))

    # Assign indices based on sorted order
    for i, ev in enumerate(merged):
        vname = ev.get('venue', '') or guess_venue(ev)
        if vname and vname in venue_map:
            venue_map[vname]['indices'].append(i)

    venues = []
    for vname, vdata in sorted(venue_map.items(), key=lambda x: -x[1]['count']):
        vdata['categories'] = sorted(vdata['categories'])
        # Find a good image — use the first event's image for this venue
        for idx in vdata['indices']:
            if idx < len(merged) and merged[idx].get('image_url'):
                vdata['image'] = merged[idx]['image_url']
                break
        if not vdata.get('image'):
            vdata['image'] = ''
        venues.append(vdata)

    if args.dry_run:
        log("\n── DRY RUN — no files written ──")
        log(f"Would write: {len(merged)} events, {len(venues)} venues")
        log(f"  +{len(new_events)} new / ~{updated} updated / {duplicates} dups")
        print(json.dumps({"events": len(merged), "venues": len(venues), "new": len(new_events), "updated": updated, "duplicates": duplicates}, indent=2))
        return

    # Write events.json
    with open(EVENTS_PATH, 'w') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    log(f"Written: {EVENTS_PATH} ({len(merged)} events)")

    # Also write venues.json for reference
    venues_path = PROJECT_DIR / "venues.json"
    with open(venues_path, 'w') as f:
        json.dump(venues, f, ensure_ascii=False, indent=2)
    log(f"Written: {venues_path} ({len(venues)} venues)")

    # Summary
    summary = {
        "events_total": len(merged),
        "venues_total": len(venues),
        "new_events": len(new_events),
        "events_updated": updated,
        "duplicates_skipped": duplicates,
        "sources": list(set(e.get('source_id', '') for e in merged)),
    }
    print(json.dumps(summary, indent=2))


def guess_venue(ev: dict) -> str:
    """Try to extract venue from address/description."""
    addr = ev.get('address', '') or ''
    desc = ev.get('description', '') or ''
    text = addr + ' ' + desc

    known_venues = [
        'Le Vox', 'Little Bar', 'Monkey Bar', 'Moo Bar', 'Le Chaudron',
        'Chambre 9', 'Le Chambre 9', 'Bar des Sports', 'Bistro des Sports',
        'La Caleche', 'Le Monchu', 'Le Bivouac', 'Le Caveau',
        'Espace Michel Croz', 'Espace Animation',
        'La Folie Douce', 'Le Royal Bar',
    ]
    for v in known_venues:
        if v.lower() in text.lower():
            return v
    return ''


def guess_type(category: str) -> str:
    type_map = {
        'Cinema': 'Cinéma',
        'concert': 'Bar / Concert',
        'exhibition': 'Exposition',
        'theatre': 'Théâtre',
        'sport': 'Sport',
        'market': 'Marché',
        'family': 'Famille',
    }
    return type_map.get(category, 'Lieu')


if __name__ == '__main__':
    main()
