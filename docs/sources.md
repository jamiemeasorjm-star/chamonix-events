# Sources — Chamonix Events Calendar

*Last updated: 2026-07-23*

---

## Active Sources

### ✅ chamonix.net (Primary — Tier 1)

| Field | Value |
|-------|-------|
| URL | `https://www.chamonix.net/english/events` |
| Type | Drupal 9, server-rendered HTML |
| Status | Active — listing + detail scraping |
| Scraper | `scripts/chamonix_net.py` |
| Schedule | Every 6h (part of `chamonix-refresh.sh`) |
| Confidence baseline | 1.0 (high trust) |

### ✅ chamonix.com (Secondary — Tier 1)

| Field | Value |
|-------|-------|
| URL | `https://www.chamonix.com/evenements/evenements-et-manifestations` |
| Type | Drupal, JS-rendered content |
| Status | Active — listing only. Detail pages JS-rendered (broken for httpx). |
| Scraper | `scripts/chamonix_com.py` |
| Schedule | Every 24h (part of `chamonix-refresh.sh`) |
| Confidence baseline | 1.0 (high trust) |

### ✅ Le Vox cinema (Tier 1)

| Field | Value |
|-------|-------|
| URL | `https://cinemavox-chamonix.com/fichier/programme.pdf` |
| Type | PDF parsed weekly. Posters enriched via TMDB + AlloCiné |
| Status | Active |
| Scraper | `scripts/vox_pdf.py` |
| Schedule | Every 168h (weekly, part of `chamonix-refresh.sh`) |
| Confidence baseline | 1.0 (high trust) |

### 🟡 manual_submission (Tier 3 — review only)

| Field | Value |
|-------|-------|
| URL | `POST /api/submit` (via `submit.html` form) |
| Type | Community submissions |
| Status | Active — always routed to review queue |
| Backend | `http_server.py` → `insert_review_item()` |
| Confidence cap | 0.55 (below 0.6 threshold → always reviewed) |

### Disabled / Planned Sources

| Source | Status | Notes |
|--------|--------|-------|
| `allocine_vox` | 🔴 Disabled | `active: false` in sources.yaml. Syntax error (T02) deferred. |
| `nightlife` | 🔴 Disabled | `active: false`. 222 legacy events rejected. Would be review-only. |
| Cultural venues | 📋 Planned | Museums, libraries (T35). |
| Hotel calendars | 📋 Planned | P4 — not started. |

### Ingestion Pipeline

```
Source → Fetch → Parse → Normalize → Validate → Score (T14) → 
  Dedupe (T11) → [confidence ≥ 0.6?] → Yes: publish / No: review queue (T26)
```

- **Storage:** SQLite (canonical). JSON files are build artefacts.
- **Dedup:** Single algorithm in `scripts/dedup.py` — keyed on `(normalized_title, start_date)`.
- **Confidence:** `source_trust × parse_quality × completeness` (T14).
- **Threshold:** Global `min_publish_confidence: 0.6` (per-source overrides in `sources.yaml`).
- **Review queue:** `review_items` table. Managed via CLI (`review_cli.py`) or API (`POST /api/review/<id>/approve|reject`).

### Scraper Health (current)

| Source | Published | Confidence | Status |
|--------|-----------|------------|--------|
| chamonix_com | 67 | ≥0.61 (Tier 1) | Healthy |
| chamonix_net | 7 | ≥0.61 (Tier 1) | Healthy |
| allocine_vox | 8 | ≥0.61 (legacy) | Disabled — no new scrapes |
| cinema | 14 films | — | Parsed weekly from PDF |
| Venues | 26 (23 with coords) | — | Seeded + geocoded |

### Missing features (for v1.1)

- RSS / iCal export
- Individual venue website scrapers (hotels)
- Cultural venue sources (museums)
- Admin dashboard (T38 — `/admin/` live on http_server)