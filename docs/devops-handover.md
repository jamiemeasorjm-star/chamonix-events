# DevOps Handover — Chamonix Events Calendar

**Date:** 2026-05-26  
**Author:** BYTE (Hermes Agent)  
**Project:** Chamonix Valley Events Aggregator  
**URL:** https://workspace.srv1626662.hstgr.cloud/chamonix/  
**Repository:** Not yet in GitHub SSOT — lives at `/opt/data/chamonix-events/` on the VPS

---

## 1. Executive Summary

The Chamonix Events project aims to aggregate events from multiple sources across the Chamonix valley into a single, filterable calendar. The frontend is functional and publicly accessible. **The data layer is the critical blocker** — the current scraper (chamonix.com) extracts titles and basic dates from the listing page, but ALL descriptions, times, prices, and venue details are empty because the target site loads its content via JavaScript. The scraper (`httpx`) cannot execute JS, so detail page parsing produces zero meaningful data.

**17 events are visible** in the default 30-day view, but none have descriptions. The frontend has been fixed with a search button and multi-day overlap filter.

---

## 2. Architecture Overview

```
+--------------+     +--------------+     +------------------+     +--------------+
|  Scraper(s)  |--->|  events.json |--->|  Hermes Workspace |--->|  Browser     |
|  (Python)    |     |  venues.json |     |  (Node proxy)    |     |  (Tailwind   |
|              |     |  (static)    |     |  port 3000 -> 8080|     |   CSS/JS)    |
+--------------+     +--------------+     +------------------+     +--------------+
                           |                        ^
                           v                        |
                    /opt/data/chamonix-events/       |
                    data/events.json                 |
                    index.html <-- served by Python  |
                    http.server on port 8080         |
                                                     |
                    HTTPS: Hostinger -> port 3000    |
                    -> Workspace -> /chamonix/ -> 8080
                    HTTP: nginx -> /chamonix/ -> 8080
```

### Deployment Details

| Component | Port | Technology | Start Command |
|-----------|------|-----------|---------------|
| Static server | 8080 | Python http.server | `cd /opt/data/chamonix-events && python3 -m http.server 8080` |
| Workspace proxy | 3000 | Node.js (serve-production.mjs) | Managed by container entrypoint |
| nginx (HTTP) | 80 | nginx | Container-managed |
| Provider HTTPS | 443 -> 3000 | Hostinger proxy | External |

### Key Files

| Path | Purpose |
|------|---------|
| `/opt/data/chamonix-events/index.html` | Frontend (Tailwind CSS, vanilla JS) |
| `/opt/data/chamonix-events/data/events.json` | Scraped event data (JSON array) |
| `/opt/data/chamonix-events/scripts/chamonix_com.py` | Scraper for chamonix.com |
| `/opt/data/chamonix-events/scripts/models.py` | Event/Venue dataclasses |
| `/opt/data/chamonix-events/docs/` | Project documentation |
| `/opt/data/scripts/serve-production.mjs` | Workspace server (has /chamonix/ proxy) |
| `/opt/data/scripts/chamonix-events-server.sh` | Server startup script |

---

## 3. Data Quality Analysis

### Current Status

| Metric | Value |
|--------|-------|
| Total events in DB | 20 |
| Events with descriptions | **0 / 20 (0%)** |
| Events with valid dates | 19 / 20 (95%) |
| Events with commune data | 20 / 20 (100%) -- all default to "Chamonix" |
| Events with time data | **0 / 20 (0%)** |
| Events with price data | **0 / 20 (0%)** |
| Events with venue names | **0 / 20 (0%)** |
| Events with images | 19 / 20 (95%) |

### Root Cause Analysis

**Problem: The scraper (`httpx` + `BeautifulSoup`) cannot extract content from chamonix.com detail pages.**

Evidence:

1. **chamonix.com is a Drupal site that renders content via JavaScript.**
   - Raw HTTP GET of a detail page returns only the HTML shell (navigation, header, footer)
   - The actual event description, date fields, venue info, and times are loaded dynamically by JS
   - `httpx` does not execute JavaScript -> `soup.select_one(".content .field--name-body")` returns `None`
   - All description selectors (`.description`, `#presentation`, `.section-presentation`) return `None`
   - All date selectors (`.field--name-field-date-debut`, `.date-display-single`, `[itemprop="startDate"]`) return `None`
   - All time selectors (`.field--name-field-heure`, `[property="schema:startTime"]`) return `None`

2. **No JSON API or REST feed available.**
   - Tested: `?_format=json` -> 406 (route only supports HTML)
   - Tested: `/jsonapi` -> empty (JSON:API not enabled)
   - Tested: `/api/events`, `/api/evenements`, `/rest/views/evenements` -> all 404
   - The site has no machine-readable data export

3. **Listing page scraping works but is limited.**
   - CSS selector `div.objet-touristique` correctly finds 20 events
   - Title, URL, and basic date string are extracted from listing cards
   - Date parsing regex handles French date formats (`13/05-24/06/26`, `27/05/2026`)
   - But dates are often partial or missing for recurring/undated events

4. **The one event with missing date ("Marche de Chamonix")** is a recurring weekly market -- the listing page shows no date range for it.

---

## 4. Solution: Switch Primary Source to chamonix.net

chamonix.net is also a Drupal site (v9.5.11) but **renders event content server-side**. Raw HTML contains full event data.

### Evidence

| Feature | chamonix.com (current) | chamonix.net (recommended) |
|---------|----------------------|---------------------------|
| JS-rendered content | Yes -- all detail content hidden | No -- server-rendered HTML |
| Events found | 20 listing cards | 12 structured events |
| Descriptions in HTML | Empty | Full descriptions |
| Dates in HTML | Not in detail pages | Start/end dates |
| Categories | Via keyword matching | Pre-categorized |
| Venue locations | Not extractable | Venue names present |
| Image URLs | og:image works | Image fields present |
| English content | French only | English descriptions |

### chamonix.net Structure

```
.node--type-event (12 events, server-rendered)
|-- .post-thumbnail -> img[data-src] (lazy-loaded images)
|-- .post-content
|   |-- h2.post-title -> a[href] (link to detail page)
|   |-- .post-meta
|   |   |-- .post-categories -> category link
|   |-- .field--name-body -> description text
```

Date extraction from listing cards works via `.node--type-event` content parsing. Example event card text:

```
Chamonix Market Day (Every Saturday)
Tradition & Markets
01-Dec-2026
Every Saturday from 08:00 to 15:00
Place du Mont Blanc, Chamonix
```

Event detail pages contain richer structured fields (Drupal field system with schema.org microdata):

```
.field--name-field-date -> .date-display-single (with datetime attribute)
.field--name-field-lieu (venue location)
[property="schema:startDate"] (ISO datetime)
[itemprop="startTime"] (time)
```

### Recommended Implementation Plan

**Phase 1 (Immediate): Build chamonix.net scraper**

Create a new scraper `scripts/chamonix_net.py` that:

1. Fetches `https://www.chamonix.net/english/events` listing page
2. Extracts all `.node--type-event` nodes (currently 12 events)
3. For each event:
   - Title from `h2.post-title a`
   - URL from same link, normalized to absolute
   - Category from `.post-categories a` text
   - Description from `.field--name-body`
   - Date from listing card content (already has human-readable dates)
   - Image from `img[data-src]` (lazy-loaded, needs `data-src` not `src`)
4. Optionally fetch detail pages for richer data (ISO dates, venue, time)
5. Merge with existing chamonix.com data (dedupe by URL, keep richer entry)
6. Export to same `data/events.json` format

**Phase 2: Headless browser for chamonix.com**

For deeper coverage, add a `Playwright`-based scraper for chamonix.com that:

1. Renders the listing page with JS
2. Clicks through to detail pages
3. Waits for content to render
4. Extracts full descriptions, dates from rendered DOM

**Phase 3: Multi-source pipeline**

Add per-venue scrapers starting with P2-P4 sources (nightlife, cultural venues, hotels).

---

## 5. Current Frontend Status

### Working
- [x] Tailwind CSS responsive design
- [x] Event cards with date, title, category, commune badges
- [x] Click-to-open source URL in new tab
- [x] Date range filter (from/to)
- [x] Category filter (dropdown)
- [x] Commune filter (dropdown)
- [x] Search button (explicit apply)
- [x] Reset button
- [x] Multi-day event overlap logic (fixed this session)
- [x] Date range label on multi-day events (e.g. "24 Apr -> 20 Jun")
- [x] Today/Tomorrow tags
- [x] Event count display

### Still Missing
- [ ] Time display (no data from scraper yet)
- [ ] Price display (no data from scraper yet)
- [ ] Venue location display (no data from scraper yet)
- [ ] Image display in cards (images exist in data but frontend doesn't render them)
- [ ] Map integration for venue locations
- [ ] Mobile swipe/pull-to-refresh
- [ ] Loading state improvements
- [ ] Error state for failed data fetch

---

## 6. Infrastructure Issues

### HTTPS Routing (Resolved)
The provider routes HTTPS traffic directly to port 3000 (Hermes Workspace), bypassing nginx. Fixed by adding a `/chamonix/` proxy route in the Workspace server (`serve-production.mjs`). This is a maintenance concern if the Workspace server is updated or replaced.

**If the Workspace server file is regenerated** (e.g. git pull in `/opt/data/hermes-workspace`), the proxy modification in `serve-production.mjs` will be lost. The script lives at `/opt/data/scripts/serve-production.mjs` (persistent bind mount) to survive git operations, so this should be safe.

### No Cron Job Set Up
The scraper is not running on a schedule. Per `docs/ingestion-flow.md`:
- P0 sources: every 6h
- P1 sources: every 12h
- P2-P4: every 24h

**Current manual command:** `cd /opt/data/chamonix-events && python3 -m scripts.chamonix_com`

### No Auto-start for Python Server
The chamonix static server (port 8080) is started manually via:
```
bash /opt/data/scripts/chamonix-events-server.sh
```
It should be added to container supervision or cron @reboot.

---

## 7. Recommended Action Items

### Critical (Blocking Data Quality)

| Priority | Task | Effort | Details |
|----------|------|--------|---------|
| P0 | Build chamonix.net scraper | 1-2h | Full descriptions, dates, venues available |
| P0 | Run scraper on schedule | 30m | Set up cron job for every 6h |
| P0 | Add image display to frontend | 30m | `index.html` already has `image_url` -- add `<img>` to cards |

### High (Completeness)

| Priority | Task | Effort | Details |
|----------|------|--------|---------|
| P1 | Auto-start Python server | 15m | Add to supervisord or container entrypoint |
| P1 | Add Playwright scraper for chamonix.com | 3-4h | Requires Playwright + browsers in Docker |
| P1 | Fix "Marche de Chamonix" date | 15m | Recurring weekly market |
| P1 | Add venue detail scraping from chamonix.net | 1h | Detail pages have schema.org data |

### Medium (Quality of Life)

| Priority | Task | Effort | Details |
|----------|------|--------|---------|
| P2 | Add loading skeleton to frontend | 30m | Current "Loading events..." is minimal |
| P2 | Add error handling for fetch failures | 15m | Display exists but could be prettier |
| P2 | Separate commune extraction per event | 30m | Currently all default to "Chamonix" |
| P2 | Add venue sources (nightlife, hotels) | 4-6h | Per docs/sources.md list of 22+ venues |

### Low (Nice-to-Have)

| Priority | Task | Effort | Details |
|----------|------|--------|---------|
| P3 | Map integration with venue pins | 2-3h | Leaflet.js or Mapbox |
| P3 | RSS/ical export | 1-2h | Generate `.ics` from events.json |
| P3 | Subscribable calendar feed | 2h | WebCal link |
| P4 | Multi-language support | 2-3h | FR/EN toggle |
| P4 | Push notifications for new events | 3-4h | Via Telegram/webhook |

---

## 8. Quick Fixes Applied This Session

| Fix | Details |
|-----|---------|
| Search button | Added explicit `#search-btn` with `applyFilters()` function |
| Multi-day filter overlap | Changed from single-date check to overlap: `eventStart <= endVal AND eventEnd >= startVal` |
| Date range label on cards | Multi-day events show "24 Apr -> 20 Jun" format |
| Date auto-fill on partial range | If user sets start date without end, auto-fills +30 days |
| Broken unicode escapes in JS | Fixed `\\U0001f4cd` -> actual emoji characters |
| External HTTPS access | Added /chamonix/ proxy in Workspace server (port 3000 -> 8080) |

---

## 9. Verification Checklist for Next Deploy

After implementing the chamonix.net scraper:

- [ ] `cd /opt/data/chamonix-events && python3 -m scripts.chamonix_net --dry-run` -- shows events with descriptions
- [ ] `python3 -m scripts.chamonix_net` -- writes events.json with populated fields
- [ ] `grep -c '"description"' data/events.json` -- should have >0 non-empty descriptions
- [ ] Browse `https://workspace.srv1626662.hstgr.cloud/chamonix/` -- cards show descriptions
- [ ] `cronjob action=create` -- scraper runs every 6h
- [ ] `bash /opt/data/scripts/chamonix-events-server.sh` -- server auto-starts on reboot

---

## 10. Data Sources Roadmap

From `docs/sources.md`:

```
Priority  Status  Source
P0        BROKEN  chamonix.com (JS-rendered, no API)
P0        TODO    chamonix.net (to be built)
P1        TODO    chamonix.net English events detail
P2        PLANNED 22x nightlife venues
P3        PLANNED Cultural venues (museums, cinema)
P4        PLANNED Hotel event calendars
```

---

## Appendix A: Commands Reference

```bash
# Run scraper (dry run)
cd /opt/data/chamonix-events && python3 -m scripts.chamonix_com --dry-run

# Run scraper (live -- overwrites events.json)
cd /opt/data/chamonix-events && python3 -m scripts.chamonix_com

# Start static server
bash /opt/data/scripts/chamonix-events-server.sh

# Restart Workspace server (if proxy modification needs reload)
kill $(ps aux | grep 'serve-production.mjs' | grep -v grep | awk '{print $2}')

# Test frontend locally
curl -s http://localhost:3000/chamonix/ | head

# Test data file
curl -s https://workspace.srv1626662.hstgr.cloud/chamonix/data/events.json | python3 -m json.tool | head
```

## Appendix B: chamonix.net Detail Page Structure

When building the scraper, detail pages (e.g. `https://www.chamonix.net/english/events/chamonix-market-day`) contain:

- Schema.org JSON-LD with exact dates, descriptions, location
- `.field--name-field-date` with ISO date values
- `.field--name-field-lieu` with venue name
- `.field--name-body` with full HTML description
- Meta `og:image` for event photos
- Breadcrumb with category hierarchy

These provide richer data than the listing page alone.
