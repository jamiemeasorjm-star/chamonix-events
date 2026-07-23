# MVP v1 — Scope (2026-07-23: ✅ Complete)

All Must Have and Should Have items are implemented. The site is live at port 8090/8095 with 82 published events, 26 venues, and a full review pipeline.

## Must Have

- [x] Homepage feed: rolling list of events sorted by date
- [x] Date range picker (start → end)
- [x] Filters: category, commune, venue
- [x] Event detail modal (title, date, time, venue, description, source link)
- [x] Venue section (list of venues with event counts)
- [x] Ingestion from 3+ sources (chamonix.net, chamonix.com, vox_pdf)
- [x] Review queue (low-confidence events flagged for manual review — T26/T27)
- [x] JSON export pipeline (events.json, venues.json, cinema_events.json)

## Should Have

- [x] About/trust page (`/about.html` — sources, methodology, confidence ladder)
- [x] Basic search (title, venue name)
- [x] "This week" / "This weekend" quick filters
- [x] Responsive mobile layout (bottom tab nav, single-column cards)
- [x] i18n (EN/FR/ES/HU/SV — browser-detect + toggle)
- [x] Map view (Leaflet with 23 venue markers, deferred load)
- [x] Submit events form (`/submit.html` → review queue)
- [x] Cinema section (day picker, poster grid, showtime buttons)
- [x] Health endpoint (`/healthz` with build age)

## Out of Scope (v1)

- User accounts / login
- Itinerary builder
- Payment processing
- Full CMS
- iCal/ICS export (planned for v1.1)
- Notifications

## Implementation

The project used a phased ticket system (T01–T40):

| Phase | Focus | Status |
|-------|-------|--------|
| Phase 1 | Pipeline & runtime stability (T01–T09) | ✅ Done |
| Phase 2 | Data model & governance (T10–T19) | ✅ Done |
| Phase 3 | Frontend, i18n, venues, review (T20–T29) | ✅ Done |
| Phase 4 | Nightlife, submit, ops (T30–T40) | 🔶 Mostly done |

See `docs/sources.md` for source details and `scripts/gate.py` for governance rules.