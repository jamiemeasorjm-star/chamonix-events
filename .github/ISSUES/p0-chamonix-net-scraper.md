---
name: P0 — Build chamonix.net scraper, add image rendering, set up cron
about: MVP data pipeline — switch primary source to chamonix.net, get real data flowing
title: 'P0: Build chamonix.net scraper, add image rendering, set up ingestion schedule'
labels: 'P0, scraper, frontend, infra'
assignees: ''
---

## Description

The current scraper (`scripts/chamonix_com.py`) finds 20 event URLs from chamonix.com but produces **zero descriptions, zero times, zero venue names** because chamonix.com loads all detail content via JavaScript. `httpx` + BeautifulSoup cannot extract JS-rendered fields.

Investigation confirmed that **chamonix.net** (Drupal 9, server-rendered) has 12 well-structured events with full descriptions, dates, times, venue names, and contact info — all in raw HTML, no JS engine needed.

This issue builds the primary scraper around chamonix.net, wires up image display in the frontend (images already exist in data but aren't rendered), and sets up a cron schedule for automated ingestion.

## Scope

### In-scope
1. New scraper `scripts/chamonix_net.py` — scrape listing page + detail pages
2. Merge output into the existing `data/events.json` format
3. Frontend: render `image_url` in event cards
4. Cron job: run scraper every 6 hours
5. Commit all changes to GitHub via PR

### Out-of-scope
- Playwright / headless browser for chamonix.com (deferred until MVP stable)
- chamonix.com scraper improvements (deferred)
- Multi-source merging logic (chamonix.net becomes primary; existing chamonix.com data kept as secondary)
- Map integration, PWA, notifications

## Data sources verified

### chamonix.net — listing page (`/english/events`)
- 12 `.node--type-event` elements
- Captures: title, URL, category, description, image (all server-rendered)
- CSS selectors: `h2.post-title a`, `.post-categories a`, `.field--name-body`, `img[data-src]`

### chamonix.net — detail pages (`/english/events/{slug}`)
- Richer structured fields, all in raw HTML:
  - `.event-datetimes` — date + time combined string
  - `.event-dates` — date range
  - `.event-times` — time range
  - `.event-location` — venue + address
  - `.event-venue` — venue name
  - `.event-address` — full address
  - `.event-contact` — phone number
  - `.event-website` — website URL
  - `og:image` — image URL
- **Important:** Classes are custom (not Drupal field defaults). No JSON-LD present.
- Description can be parsed from `.node__content` or the listing card's `.field--name-body`

## Likely files

```
scripts/chamonix_net.py      # New scraper (model after chamonix_com.py structure)
scripts/models.py            # Update if new fields needed (e.g. contact_phone, website)
data/events.json             # Overwritten on each run (output)
index.html                   # Add <img> tag to event card template
```

## Requirements

1. Run standalone: `python3 -m scripts.chamonix_net` produces `data/events.json`
2. Dry-run mode: `--dry-run` prints parsed events without writing
3. Export format must match current `events.json` schema (see `docs/schema.md` and `scripts/models.py:Event`)
4. Images from `img[data-src]` must be converted to absolute URLs
5. Detail page fetching must be optional (flag `--no-detail` to skip detail pages, use listing data only)
6. Error handling: if a detail page fails, fall back to listing-card data for that event
7. If chamonix.com data exists, merge: prefer chamonix.net entries by URL, keep chamonix.com entries that don't overlap

## Frontend change

In `index.html`, the event card template currently skips `image_url`. Add an `<img>` tag above the card content area. It should:
- Render the image as a card header/hero
- Be optional (events without images still render cleanly)
- Be responsive (constrain height, use `object-cover`)

## Cron setup

```
0 */6 * * * cd /opt/data/chamonix-events && python3 -m scripts.chamonix_net --no-detail >> /opt/data/logs/chamonix-scraper.log 2>&1
```

The `--no-detail` flag is preferred for scheduled runs (faster, fewer HTTP requests). Per docs/ingestion-flow.md: P0 sources every 6h.

## Acceptance Criteria

- [ ] `python3 -m scripts.chamonix_net --dry-run` prints 10+ events with non-empty descriptions
- [ ] `python3 -m scripts.chamonix_net` writes `data/events.json` with descriptions, images, dates populated
- [ ] `python3 -c "import json; d=json.load(open('data/events.json')); print(sum(1 for e in d if e.get('description','').strip()))"` outputs >0
- [ ] Frontend at `https://workspace.srv1626662.hstgr.cloud/chamonix/` shows images on at least some event cards
- [ ] `crontab -l | grep chamonix` shows the 6h schedule
- [ ] `cd /opt/data/chamonix-events && git status --short` shows only expected files modified
- [ ] PR opened against `main` with all changes reviewed and mergeable

## Technical Notes

- `chamonix_com.py` already has the pattern for httpx + BeautifulSoup, CLI args, dry-run, dedup, event normalization, and JSON export. Use it as a template.
- The `Event` dataclass in `models.py` may need new optional fields: `contact_phone`, `website`. These can be `None` for chamonix.com events.
- `data/venues.json` currently has `[]` — venue extraction can be a follow-up.
- Python server on port 8080 needs no changes; it serves `events.json` already.
- Workspace proxy on port 3000 needs no changes — it proxies `/chamonix/` to port 8080.

## Risk Level

- [ ] R1 (cosmetic / docs)
- [x] R2 (scraper changes, schema, ingestion logic, frontend, deployment/cron)

## Trigger

/opencode implement this task
