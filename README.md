# Chamonix Events 🏔️

A rolling events calendar for Chamonix — aggregated from official tourism sites, cinema PDF, and community submissions. Built for visitors planning their week and locals who want a unified view of what's on.

**Status:** Live (74 published events, 26 venues, 14 cinema films)

## What it does

- Aggregates events from chamonix.net, chamonix.com, and Le Vox cinema PDF
- Rolling date-range calendar with filters (dates, categories, search, quick week/weekend/month)
- Cinema section with day picker, poster grid, and showtime buttons
- Venue section with map (23 geocoded venues with Leaflet markers)
- Language switching (EN/FR/ES/HU/SV) with bilingual event titles
- Confidence-based review pipeline — low-confidence events go to operator review queue
- Event submission form at `/submit.html` — community submissions land in review queue
- Operator dashboard at `/admin/` with live source health and queue counts
- i18n translation job (FR→EN via OpenRouter for event descriptions)

## Tech stack

- **Ingestion:** Python scrapers (cron-driven, 6h/24h/168h cadences)
- **Storage:** SQLite (canonical) + JSON build artefacts
- **Frontend:** Static HTML + custom dark theme CSS (Inter + Playfair Display fonts)
- **Server:** Python `http_server.py` with `/healthz`, `/api/review/*`, `/api/submit`, `/admin/`
- **Serving:** Port 8090 (http_server, supervised) + port 8095 (nginx reverse proxy)
- **Review:** `review_cli.py` CLI + REST API (approve/reject) + auto-publish threshold (0.6)
- **Maps:** Leaflet.js (deferred load on first map click)
- **Confidence:** `trust × parse_quality × completeness` per-source scoring

## Project layout

```
chamonix-events/
├── build.py                  # Static site builder (reads SQLite → writes HTML)
├── index.html.template       # Main page template with EVENTS/VENUES/CINEMA_DATA placeholders
├── submit.html.template      # Event submission form (POST /api/submit)
├── about.html.template       # About/trust page (sources, methodology)
├── review.html.template      # Review queue page
├── sources.yaml              # Source registry (trust levels, cadence, threshold)
├── scripts/
│   ├── chamonix_net.py       # Scraper for chamonix.net
│   ├── chamonix_com.py       # Scraper for chamonix.com (listing only)
│   ├── vox_pdf.py            # Cinema PDF parser
│   ├── storage.py            # SQLite storage layer (events, venues, review_items)
│   ├── http_server.py        # HTTP server with healthz, review API, submit, admin
│   ├── models.py             # Dataclasses + helpers
│   ├── sources.py            # Source registry loader
│   ├── scoring.py            # Confidence scoring (T14)
│   ├── dedup.py              # Unified cross-source dedup (T11)
│   ├── review_cli.py         # Operator CLI for review queue (T27)
│   ├── gate.py               # Governance pre-commit hook (T33)
│   └── translate_job.py      # FR→EN translation (P1)
├── data/
│   ├── chamonix.db           # SQLite database
│   ├── builds/               # Build snapshots (last 30)
│   └── last_build.json       # Build metadata for /healthz
└── docs/
    ├── sources.md            # Source registry documentation
    ├── mvp-v1.md             # MVP scope and status
    ├── schema.md             # Data model
    └── ingestion-flow.md     # Pipeline steps
```

## Quick commands

```bash
# Build static site
./venv/bin/python3.11 build.py

# Run HTTP server
python3 -m scripts.http_server

# Review queue CLI
python3 -m scripts.review_cli list
python3 -m scripts.review_cli approve <id> --by=operator
python3 -m scripts.review_cli reject <id> --note="reason" --by=operator

# Full pipeline refresh
bash /root/.hermes/scripts/chamonix-refresh.sh
```

## Non-goals

- No itinerary builder
- No user accounts
- No payment processing
- No "super app" replacing official venue sites

## Project docs

See [docs/](docs/) for the full product brief, roadmap, schema, and architecture.