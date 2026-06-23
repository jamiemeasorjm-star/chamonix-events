#!/usr/bin/env python3
"""Chamonix Facebook Event Scraper - Stealth mode. Extracts event posts from FB pages."""

import json, os, sys, time, random, re
from datetime import datetime
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).parent

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
window.chrome = { runtime: {} };
"""

def load_config():
    with open(SCRIPT_DIR / 'targets.yaml') as f:
        return yaml.safe_load(f)

def load_cookies():
    path = SCRIPT_DIR / 'session' / 'facebook-cookies.txt'
    if not path.exists():
        print("ERROR: No cookies file found at", path)
        return []
    cookies = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 7:
                continue
            cookies.append({
                'domain': parts[0], 'path': parts[2],
                'secure': parts[3].lower() == 'true',
                'name': parts[5], 'value': parts[6],
                'httpOnly': False, 'sameSite': 'Lax',
            })
    return cookies

def random_delay(a=2, b=5):
    time.sleep(random.uniform(a, b))

def scrape_page(page, url, max_posts=20):
    print(f"  Navigating to {url}")
    page.goto(url, wait_until='domcontentloaded', timeout=30000)
    
    # Wait for feed content to render
    wait_start = time.time()
    while time.time() - wait_start < 15:
        random_delay(2, 3)
        
        # Check if we have posts
        post_count = page.evaluate("""
            () => {
                const articles = document.querySelectorAll('[role="article"]');
                let count = 0;
                articles.forEach(a => {
                    if (a.innerText && a.innerText.trim().length > 50) count++;
                });
                return count;
            }
        """)
        print(f"    Waiting for content... {post_count} posts so far")
        
        if post_count >= 3:
            break
        
        # Scroll
        page.evaluate('window.scrollBy(0, 500)')
    
    # Now extract posts
    posts = page.evaluate("""
        (maxPosts) => {
            const results = [];
            const articles = document.querySelectorAll('[role="article"]');
            
            articles.forEach(el => {
                const text = el.innerText || '';
                if (text.length < 40) return;
                if (text.includes('Facebook menu') || text.includes('Meta AI')) return;
                
                const imgs = [];
                el.querySelectorAll('img').forEach(img => {
                    const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
                    if (src && src.length > 40 && src.startsWith('http') && !imgs.includes(src)) {
                        imgs.push(src);
                    }
                });
                
                const links = [];
                el.querySelectorAll('a').forEach(a => {
                    const h = a.href || '';
                    if (h && (h.includes('/events/') || h.includes('/posts/') || h.includes('/photos/'))) {
                        links.push(h);
                    }
                });
                
                results.push({
                    text: text.substring(0, 3000),
                    images: imgs.slice(0, 4),
                    links: links.slice(0, 3),
                });
            });
            
            return results.slice(0, maxPosts);
        }
    """, max_posts)
    
    return posts

def parse_event(post, page_config):
    text = post.get('text', '')
    if not text:
        return None
    
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(lines) < 2:
        return None
    
    # Title is usually the first substantive line
    title = lines[0]
    if len(title) < 3:
        title = lines[1] if len(lines) > 1 else title
    title = title[:150]
    
    # Find French dates
    month_map = {
        'janvier':'01','fevrier':'02','février':'02','mars':'03','avril':'04','mai':'05',
        'juin':'06','juillet':'07','aout':'08','août':'08','septembre':'09','octobre':'10',
        'novembre':'11','decembre':'12','décembre':'12'
    }
    
    event_date = ''
    for pattern in [
        r'(\d{1,2})\s*(juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre|janvier|f[eé]vrier|mars|avril|mai)\s*(\d{4})?',
        r'(\d{1,2})/(\d{1,2})/(\d{4})',
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            event_date = m.group(0)
            break
    
    return {
        'title': title,
        'description': text[:2000],
        'date_posted': datetime.now().isoformat(),
        'event_date': event_date,
        'image_url': post.get('images', [''])[0],
        'source_url': post.get('links', [''])[0],
        'page_name': page_config['name'],
        'category': page_config.get('category', 'other'),
        'venue': page_config.get('venue', ''),
        'source': 'facebook',
    }

def main():
    config = load_config()
    cookies = load_cookies()
    if not cookies:
        print("ERROR: No cookies loaded.")
        sys.exit(1)
    
    enabled_pages = [p for p in config['pages'] if p.get('enabled', False)]
    print(f"Loaded {len(cookies)} cookies, {len(enabled_pages)} enabled pages")
    
    all_events = []
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        ctx = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='en_GB',
        )
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.add_init_script(STEALTH_JS)
        
        for target in enabled_pages:
            print(f"\n=== {target['name']} ===")
            try:
                posts = scrape_page(page, target['url'], config['settings'].get('max_posts_per_page', 20))
                print(f"  Extracted {len(posts)} posts")
                
                for post in posts:
                    event = parse_event(post, target)
                    if event:
                        all_events.append(event)
                
            except Exception as e:
                print(f"  ERROR: {e}")
            
            random_delay(*config['settings'].get('human_delay_range', [3, 7]))
        
        browser.close()
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = SCRIPT_DIR / 'data' / f'facebook_{timestamp}.json'
    with open(out_path, 'w') as f:
        json.dump(all_events, f, ensure_ascii=False, indent=2)
    
    print(f"\nDone. {len(all_events)} events -> {out_path}")

if __name__ == '__main__':
    main()
