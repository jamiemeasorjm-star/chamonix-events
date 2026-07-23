# Chamonix Events — Ticket Tracking

This directory tracks project tickets and their status. Each file is a markdown plan per ticket group.

## Ticket numbering

- **T01–T09**: Phase 1 — Pipeline & runtime stability ✅
- **T10–T19**: Phase 2 — Data model & governance ✅
- **T20–T29**: Phase 3 — Frontend, i18n, venues, review ✅
- **T30–T40**: Phase 4 — Nightlife, submit, ops ✅
- **T41–T50**: Extended — PWA, CI, pagination, automation ✅
- **T51+**: Current/active work

## Current status

| Area | Status | Detail |
|------|--------|--------|
| **Published events** | ✅ 108 live | 79 nightlife + 11 cultural + 10 chamonix_net + 8 allocine_vox |
| **Cinema** | ✅ 14 films | PDF + allocine_vox sources |
| **Venues** | ✅ 26 (23 geocoded) | Map rendering with Leaflet |
| **Site serving** | ✅ 8090 + 8095 | http_server (systemd) + nginx reverse proxy |
| **Admin dashboard** | ✅ | /admin/ with metrics, source table, review queue |
| **Review pipeline** | ✅ | Auto-triage + manual approval |
| **Build pipeline** | ✅ | Static site generation + event detail pages |
| **PWA** | ✅ | manifest.json + sw.js |
| **Pagination** | ✅ | Client-side, 10 events/page |
| **Detail scraper** | 🔴 Fixed but not tested | chamonix.com sitemap URL structure changed → commune-based paths |
| **AlloCiné source** | 🟡 Disabled | `active: false` in sources.yaml (deferred) |
| **Commit health** | ✅ Committed | All 76 files, 11,422 insertions committed |