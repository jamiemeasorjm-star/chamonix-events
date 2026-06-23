#!/usr/bin/env python3
"""
Chamonix Facebook Graph API Scraper

Two-phase scraping per page:
  1. /{page_id}/events  — structured Facebook Events (official events)
  2. /{page_id}/posts   — text posts with embedded event info

Outputs to: data/facebook_{timestamp}_raw.json
"""

import json, os, sys, time, re, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

TOKEN = os.environ.get("FACEBOOK_PAGE_TOKEN", "")
API_BASE = "https://graph.facebook.com/v22.0"

MONTH_MAP_FR = {
    'janvier': '01', 'février': '02', 'fevrier': '02', 'mars': '03',
    'avril': '04', 'mai': '05', 'juin': '06', 'juillet': '07',
    'août': '08', 'aout': '08', 'septembre': '09', 'octobre': '10',
    'novembre': '11', 'décembre': '12', 'decembre': '12',
}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def api_get(path: str, params: dict = None) -> Optional[dict]:
    """Make a Graph API GET request. Returns dict or None on error."""
    if not TOKEN:
        log("ERROR: FACEBOOK_PAGE_TOKEN not set. Create .env or export it.")
        return None
    if params is None:
        params = {}
    params["access_token"] = TOKEN
    qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    url = f"{API_BASE}/{path}?{qs}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        log(f"  HTTP {e.code} for {path}: {body}")
        return None
    except Exception as e:
        log(f"  Request failed for {path}: {e}")
        return None


def fetch_all(path: str, params: dict = None, max_pages: int = 2) -> list:
    """Fetch a paginated Graph API endpoint. Returns all items."""
    items = []
    data = api_get(path, params)
    if not data:
        return items
    items.extend(data.get("data", []))
    page = 0
    while "paging" in data and "next" in data["paging"] and page < max_pages:
        time.sleep(0.3)
        try:
            req = urllib.request.Request(data["paging"]["next"])
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            items.extend(data.get("data", []))
            page += 1
        except Exception as e:
            log(f"  Pagination error: {e}")
            break
    return items


# ─── Date parsing ──────────────────────────────────────────────

FR_MONTHS = '|'.join(MONTH_MAP_FR.keys())
DATE_PATTERNS = [
    # "24 juin 2026" or "24 juin"
    re.compile(r'(\d{1,2})\s*(' + FR_MONTHS + r')\s*(\d{4})?', re.IGNORECASE),
    # "24/06/2026" or "24/06"
    re.compile(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?'),
    # "2026-06-24"
    re.compile(r'(\d{4})-(\d{1,2})-(\d{1,2})'),
    # "samedi 24 juin" / "vendredi 24"
    re.compile(r'(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+(\d{1,2})\s+(' + FR_MONTHS + r')', re.IGNORECASE),
]


def parse_date_from_text(text: str) -> Optional[str]:
    """Try to extract an ISO date (YYYY-MM-DD) from French text."""
    if not text:
        return None
    today = datetime.now()
    year_now = today.year

    for pat in DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        groups = m.groups()

        if len(groups) == 3 and groups[2] and groups[0].isdigit() and groups[2].isdigit() and int(groups[0]) > 31:
            # YYYY-MM-DD
            return f"{groups[0]}-{int(groups[1]):02d}-{int(groups[2]):02d}"
        elif len(groups) == 3 and groups[2] and groups[2].isdigit() and int(groups[2]) > 31:
            # DD/MM/YYYY
            return f"{groups[2]}-{int(groups[1]):02d}-{int(groups[0]):02d}"
        elif len(groups) == 3 and groups[1] and groups[1].lower() in MONTH_MAP_FR:
            # DD month YYYY
            month = MONTH_MAP_FR[groups[1].lower()]
            year = groups[2] if groups[2] else str(year_now)
            return f"{year}-{month}-{int(groups[0]):02d}"
        elif len(groups) == 2:
            # DD/month (no year)
            month_num = None
            day_str = groups[0]
            month_str = groups[1].lower()
            if month_str in MONTH_MAP_FR:
                month_num = MONTH_MAP_FR[month_str]
            elif month_str.isdigit():
                month_num = f"{int(month_str):02d}"
            if month_num and day_str.isdigit():
                year = str(year_now)
                return f"{year}-{month_num}-{int(day_str):02d}"
        elif len(groups) == 3 and not groups[2]:
            # DD/MM (no year)
            month_num = f"{int(groups[1]):02d}" if groups[1].isdigit() else None
            if not month_num:
                continue
            return f"{year_now}-{month_num}-{int(groups[0]):02d}"

    return None


def parse_fb_datetime(fb_str: str) -> Optional[dict]:
    """Parse a Facebook datetime string into {iso, date, time}."""
    if not fb_str:
        return None
    try:
        # FB returns ISO 8601 with timezone
        if 'T' in fb_str and '+' in fb_str:
            fb_str = fb_str.split('+')[0]
        elif 'T' in fb_str and fb_str.endswith('Z'):
            fb_str = fb_str[:-1]
        dt = datetime.fromisoformat(fb_str) if 'T' in fb_str else datetime.strptime(fb_str, '%Y-%m-%d')
        return {
            'iso': dt.strftime('%Y-%m-%d'),
            'date': dt.strftime('%Y-%m-%d'),
            'time': dt.strftime('%H:%M') if 'T' in fb_str else '',
        }
    except:
        return None


# ─── Scraping Phases ──────────────────────────────────────────

def scrape_events(page_id: str, page_config: dict) -> list:
    """Phase 1: Fetch structured Facebook Events via /events endpoint."""
    log(f"  Phase 1: Fetching structured events...")
    raw = fetch_all(f"{page_id}/events", {
        'fields': 'name,description,start_time,end_time,place{name,location},cover,id,permalink_url',
        'limit': 50,
    })
    results = []
    for ev in raw:
        start = parse_fb_datetime(ev.get('start_time'))
        end = parse_fb_datetime(ev.get('end_time')) if ev.get('end_time') else None
        place = ev.get('place', {}) or {}
        loc = place.get('location', {}) or {}
        address = loc.get('street', '') if loc.get('street') else place.get('name', '')
        results.append({
            '_source': 'fb_event',
            '_page_name': page_config['name'],
            'title': ev.get('name', ''),
            'description': ev.get('description', ''),
            'start_date': start['date'] if start else '',
            'end_date': end['date'] if end else '',
            'time': start['time'] if start and start.get('time') else '',
            'address': address,
            'venue': page_config.get('venue', ''),
            'category': page_config.get('category', 'other'),
            'image_url': ev.get('cover', {}).get('source', '') if ev.get('cover') else '',
            'source_url': ev.get('permalink_url', ''),
            'page_id': page_id,
            'fb_id': ev.get('id', ''),
            'commune': 'Chamonix',
            'confidence': 0.95,
        })
    log(f"    -> {len(results)} structured events")
    return results


def scrape_posts(page_id: str, page_config: dict) -> list:
    """Phase 2: Fetch recent posts and parse embedded event mentions."""
    log(f"  Phase 2: Fetching recent posts...")
    raw = fetch_all(f"{page_id}/posts", {
        'fields': 'message,created_time,full_picture,permalink_url',
        'limit': 25,
    }, max_pages=1)
    results = []
    today = datetime.now()
    cutoff = today - timedelta(days=90)

    for post in raw:
        msg = post.get('message', '') or ''
        created = parse_fb_datetime(post.get('created_time'))
        if created:
            try:
                post_dt = datetime.strptime(created['date'], '%Y-%m-%d')
                if post_dt < cutoff:
                    continue
            except:
                pass

        # For posts that are clearly event announcements
        event_keywords = ['concert', 'soirée', 'soiree', 'live music', 'dj set', 
                         'spectacle', 'show', 'festival', 'afterwork', 'after-work',
                         'scène', 'scene', 'invite', 'party', 'soir']

        has_keyword = any(kw in msg.lower() for kw in event_keywords)
        date_found = parse_date_from_text(msg)

        if not has_keyword and not date_found:
            continue

        # Try to extract a title (first substantive line)
        lines = [l.strip() for l in msg.split('\n') if l.strip()]
        title = lines[0][:150] if lines else page_config['name']
        # Skip if title is just a URL or very short
        if title.startswith('http') or len(title) < 5:
            title = page_config['name'] + ' - Event'

        results.append({
            '_source': 'fb_post',
            '_page_name': page_config['name'],
            'title': title,
            'description': msg[:3000],
            'start_date': date_found or '',
            'end_date': '',
            'time': '',
            'address': '',
            'venue': page_config.get('venue', ''),
            'category': page_config.get('category', 'concert'),
            'image_url': post.get('full_picture', ''),
            'source_url': post.get('permalink_url', ''),
            'page_id': page_id,
            'fb_id': post.get('id', ''),
            'commune': 'Chamonix',
            'confidence': 0.7 if has_keyword else 0.5,
        })
    log(f"    -> {len(results)} post-based events")
    return results


def scrape_page(page_id: str, page_config: dict) -> list:
    """Scrape a single Facebook page for events."""
    log(f"=== {page_config['name']} (ID: {page_id}) ===")
    all_events = []

    # Phase 1: structured events
    structured = scrape_events(page_id, page_config)
    all_events.extend(structured)

    # Phase 2: post-based events (only if no structured events found, or always)
    if page_config.get('category') in ('concert', 'nightlife', 'other'):
        posts = scrape_posts(page_id, page_config)
        all_events.extend(posts)

    time.sleep(0.5)
    return all_events


# ─── Main ─────────────────────────────────────────────────────

def load_config() -> dict:
    import yaml
    path = SCRIPT_DIR / 'facebook_targets.yaml'
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    log("Chamonix Facebook Graph API Scraper")
    log(f"Token loaded: {'yes' if TOKEN else 'no'} ({'SET' if TOKEN else 'MISSING'})")
    if not TOKEN:
        log("ERROR: No token found. Set FACEBOOK_PAGE_TOKEN in .env or environment.")
        sys.exit(1)

    config = load_config()
    enabled = [p for p in config['pages'] if p.get('enabled') and p.get('page_id') and not p['page_id'].startswith('PLACEHOLDER_')]
    disabled = [p for p in config['pages'] if not p.get('enabled') or not p.get('page_id') or p['page_id'].startswith('PLACEHOLDER_')]

    log(f"Pages: {len(enabled)} enabled, {len(disabled)} disabled (need page IDs)")

    if not enabled:
        log("")
        log("╔══════════════════════════════════════════════════╗")
        log("║  No pages enabled — page IDs needed first.      ║")
        log("║                                                  ║")
        log("║  When you have Facebook page URLs/IDs:           ║")
        log("║  1. Edit facebook_targets.yaml                   ║")
        log("║  2. Replace PLACEHOLDER_xxx with real page IDs   ║")
        log("║  3. Set enabled: true for each page              ║")
        log("║  4. Run this script again                        ║")
        log("╚══════════════════════════════════════════════════╝")
        print(json.dumps({"status": "waiting_for_ids", "enabled": 0, "disabled": len(disabled)}, indent=2))
        return

    all_events = []
    for page in enabled:
        try:
            events = scrape_page(page['page_id'], page)
            all_events.extend(events)
        except Exception as e:
            log(f"  ERROR scraping {page['name']}: {e}")

    # Dedup by fb_id within this run
    seen_ids = set()
    unique = []
    for ev in all_events:
        fid = ev.get('fb_id', '')
        if fid and fid in seen_ids:
            continue
        if fid:
            seen_ids.add(fid)
        unique.append(ev)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = DATA_DIR / f'facebook_{timestamp}_raw.json'
    summary = {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'pages_scraped': len(enabled),
        'total_found': len(all_events),
        'total_unique': len(unique),
        'structured': sum(1 for e in unique if e['_source'] == 'fb_event'),
        'post_based': sum(1 for e in unique if e['_source'] == 'fb_post'),
        'pages': [p['name'] for p in enabled],
        'output': str(out_path),
    }

    with open(out_path, 'w') as f:
        json.dump({'meta': summary, 'events': unique}, f, ensure_ascii=False, indent=2)

    log(f"\nDone — {len(unique)} unique events ({summary['structured']} structured, {summary['post_based']} post-based)")
    log(f"Output: {out_path}")
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
