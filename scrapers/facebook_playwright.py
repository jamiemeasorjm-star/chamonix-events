#!/usr/bin/env python3
"""Facebook Playwright scraper for Chamonix events."""
import json, sys, os, time, re
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright
import yaml

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
COOKIES_FILE = SCRIPT_DIR / "session" / "facebook-cookies.txt"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def load_cookies():
    cookies = []
    if not COOKIES_FILE.exists():
        log(f"ERROR: No cookies file at {COOKIES_FILE}")
        return []
    with open(COOKIES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) >= 7:
                cookies.append({
                    'domain': parts[0], 'path': parts[2],
                    'secure': parts[3].lower() == 'true',
                    'name': parts[5], 'value': parts[6],
                    'sameSite': 'Lax',
                })
    return cookies

def load_config():
    with open(SCRIPT_DIR / 'facebook_targets.yaml') as f:
        return yaml.safe_load(f)

def scrape_events(page, url, page_config):
    events_url = url.rstrip('/') + '/events'
    log(f"  Navigating to events page...")
    try:
        page.goto(events_url, wait_until='domcontentloaded', timeout=30000)
    except Exception as e:
        log(f"  Navigation failed: {e}")
        return []
    
    for i in range(10):
        time.sleep(2)
        if 'checkpoint' in page.url or 'login' in page.url.lower():
            log(f"  CHECKPOINT: {page.url[:60]}")
            return []
        text = page.evaluate('document.body.innerText')
        if len(text) > 500 and 'upcoming' in text.lower():
            break
        page.evaluate('window.scrollBy(0, 500)')
    
    full_text = page.evaluate('document.body.innerText')
    log(f"  Page text: {len(full_text)} chars")
    
    events = parse_events_from_text(full_text, page_config)
    log(f"  Found {len(events)} event(s)")
    return events

def parse_events_from_text(text, page_config):
    events = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    # Find "Upcoming" section
    start = -1
    end = len(lines)
    for i, line in enumerate(lines):
        if line.lower() == 'upcoming':
            start = i
        if line.lower() == 'past' and start >= 0 and i > start:
            end = i
            break
    
    if start < 0:
        return events
    
    event_lines = lines[start+1:end]
    month_map = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
    year = datetime.now().year
    current = None
    
    for line in event_lines:
        m = re.match(r'\w{3},\s*(\d{1,2})\s*(\w{3})\s*at\s*(\d{2}:\d{2})\s*(UTC|UTC[+-]\d+)', line)
        if m:
            if current and current.get('title'):
                events.append(current)
            day = int(m.group(1))
            month = month_map.get(m.group(2).lower()[:3], 1)
            start_date = f"{year}-{month:02d}-{day:02d}"
            current = {
                '_source': 'fb_event', '_page_name': page_config['name'],
                'title': '', 'description': '', 'start_date': start_date,
                'end_date': '', 'time': m.group(3), 'address': '',
                'venue': page_config.get('venue', ''),
                'category': page_config.get('category', 'other'),
                'image_url': '', 'source_url': page_config.get('url', ''),
                'commune': 'Chamonix', 'confidence': 0.9,
            }
        elif current and not current['title'] and line and len(line) > 3:
            current['title'] = line[:150]
        elif current and line.startswith('Event by'):
            current['description'] = line
    
    if current and current.get('title'):
        events.append(current)
    
    return events

def main():
    log("Facebook Playwright Scraper")
    config = load_config()
    enabled = [p for p in config['pages'] if p.get('enabled') and p.get('url')]
    log(f"Pages: {len(enabled)} enabled")
    if not enabled:
        log("No enabled pages. Edit facebook_targets.yaml.")
        return
    
    cookies = load_cookies()
    if not cookies:
        sys.exit(1)
    log(f"Loaded {len(cookies)} cookies")
    
    all_events = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
        ctx = browser.new_context(viewport={'width':1280,'height':800}, user_agent='Mozilla/5.0')
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        
        for target in enabled:
            log(f"\n=== {target['name']} ===")
            try:
                events = scrape_events(page, target['url'], target)
                all_events.extend(events)
            except Exception as e:
                log(f"  ERROR: {e}")
            time.sleep(2)
        browser.close()
    
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = DATA_DIR / f'facebook_{ts}_raw.json'
    summary = {'status':'ok','timestamp':datetime.now().isoformat(),'pages_scraped':len(enabled),'total_events':len(all_events),'pages':[p['name'] for p in enabled],'output':str(out_path)}
    with open(out_path, 'w') as f:
        json.dump({'meta':summary,'events':all_events}, f, ensure_ascii=False, indent=2)
    log(f"\nDone - {len(all_events)} events -> {out_path}")
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
