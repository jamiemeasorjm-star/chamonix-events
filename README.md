# Chamonix Events 🏔️

A rolling events calendar for Chamonix — aggregated from official calendars, the mairie, venues, and nightlife sources. Built for visitors planning their week and locals who want a unified view of what's on.

**Status:** MVP definition in progress

## What it does

- Aggregates events from multiple sources
- Rolling date-range calendar with filters (dates, categories, communes, venues)
- Includes nightlife and fragmented sources where possible
- Minimal, fast, mobile-friendly frontend

## Tech stack

- **Ingestion:** Python scripts (cron-driven on VPS)
- **Data:** Static JSON exports (events, venues, meta)
- **Frontend:** Static HTML + Tailwind CSS + vanilla JS
- **Hosting:** Served from the same VPS
- **Review:** Minimal admin UI for event approval

## Non-goals (v1)

- No itinerary builder
- No complex user accounts
- No payment processing
- No "super app" replacing official sites

## Project docs

See [docs/](docs/) for the full product brief, roadmap, schema, and architecture.
