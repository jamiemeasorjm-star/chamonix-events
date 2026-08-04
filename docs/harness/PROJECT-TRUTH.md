# PROJECT-TRUTH.md — What the product truly is today

> Compact, current truth (2026-08-04). Replaces stale handover docs (which are history).
> Re-verify quarterly or on any architecture change.

## Product reality

- A **static, server-rendered HTML site** (inline JS/CSS, JSON injected into templates,
  no real client API) built by a Python pipeline from a SQLite DB that is **fully
  rewritten every 06:00 cron run** by live scrapers.
- Currently **54 published events** (of 60 DB rows) across 4 sources + a **6-film cinema
  block**. Nightlife is the largest source (26 events). ~28 events link to a geocoded venue.
- It is **NOT a durable canonical store**: each `upsert_events()` deletes all rows for a
  source and inserts what's scraped now. Nothing persists except the live snapshot.
- **Demo-vs-production:**
  - Demo-grade: dual cinema pipeline, invisible allocine source, empty venue/description
    rows publishing, hardcoded fake canonical domain, dead review UI, no content coverage
    alerts, orphaned static pages, DELETE-all durability.
  - Production-grade: the **frontend design system + interaction layer**, per-item
    translation (T55 fix verified), cinema table-wipe fix (C1), footer-timestamp fix (H1).

## Runtime architecture

```
Hermes cron (HOST)                        /docker/hermes-agent-2bpx/data/chamonix-events/
  chamonix-daily-refresh 06:00 ──► chamonix-refresh.sh (6-step, no_agent)
  chamonix-midday-rebuild  14:00 ──► chamonix-rebuild-only.sh (build.py only)
  chamonix-health-watchdog every 6h ──► chamonix-health-watchdog.sh → Ops chat (availability only)
  chamonix-drop-report 06:10 ──► chamonix-drop-report.sh  (BUILT, NEVER RUN)
  good-morning-stoic reads data/chamonix.db (repointed 08-03)
        │  executes: venv/bin/python3 (fallback /usr/bin/python3)
        ▼
  build.py + scripts/*.py  →  data/chamonix.db (SQLite, canonical-ish)
        │  outputs: index/about/review/submit/privacy .html, events/<slug>.html (425 files!),
        │           sitemap.xml, robots.txt, data/events.json, cinema_events.json, data/builds/*
        ▼
  supervisor chamonix-static → python scripts/http_server.py :8090 → nginx :8095
        ▼
  host-nginx /events/ prefix proxy (stripped then re-added in http_server)
```

- **Canonical truth location:** `data/chamonix.db`. JSON/HTML are **derived artefacts**
  (docs calling them "canonical" is false).
- **Live pipeline runner (the only scheduled one):** `chamonix-refresh.sh`
  (net P0 → com/allocine/detail/nightlife P1 → clean_past → vox_pdf P0 → build → translate 180s → health-check → nginx reapply).
- **Legacy/unwired runners:** `run.sh` (2-step), `run_all.sh` (5-step) — NOT scheduled; traps.
- **Host serving:** supervisor + container nginx + host-nginx prefix proxy.

## Source truth (from sources.yaml, current)

| source | trust | active | writes | exposes on site |
|---|---|---|---|---|
| chamonix_net | high | ✅ | events | ✅ feed |
| chamonix_com | high | ✅ | events | ✅ feed |
| chamonix_nightlife | low | ✅ | events | ✅ feed |
| allocine_vox | medium | ✅ | events (cat=Cinema) | ❌ **INVISIBLE** (filtered) |
| vox_pdf | high | ✅ | cinema_events | ✅ cinema block |
| manual_submission | low | ✅ | review_items | ❌ review removed |

publish_rules: `min_confidence:0.0`, `dedupe:true`, `exclude_title_patterns:[…]`.
Confidence is **not** a publish gate today (T55 removed it).

## Current open risks (see REMEDIATION-BACKLOG)
Fake canonical domain; dual cinema; DELETE-all durability; 425 orphan pages; dead review
UI; stale `docs/`; uncommitted/unpushed repo (ahead 11, dirty `index.html`); drop-report never fired.
