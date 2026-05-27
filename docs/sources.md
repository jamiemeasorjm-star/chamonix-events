# Sources — Chamonix Events Calendar

*Last updated: 2026-05-26*

---

## Active Sources

### ✅ chamonix.net (Primary — Tier 1)

| Field | Value |
|-------|-------|
| URL | `https://www.chamonix.net/english/events` |
| Type | Drupal 9, server-rendered HTML |
| Status | Active — listing + detail scraping |
| Scraper | `scripts/chamonix_net.py` |
| Events | 12 listing, full detail pages |
| Detail fields | Description, dates, times, venue, address, phone, website, image |
| Schedule | Every 6h (cron: `chamonix-scraper`) |
| Notes | Detail pages have custom CSS classes (`.event-datetimes`, `.event-venue`, `.event-location`, `.event-contact`). No JSON-LD or API available. |

### 🟡 chamonix.com (Secondary — Tier 1, partial)

| Field | Value |
|-------|-------|
| URL | `https://www.chamonix.com/evenements/evenements-et-manifestations` |
| Type | Drupal, JS-rendered content |
| Status | Listing only — detail pages broken (JS-rendered) |
| Scraper | `scripts/chamonix_com.py` |
| Events | 20 titles + URLs from listing page |
| Detail fields | All empty — descriptions, times, venues not extractable via httpx |
| Schedule | Manual only (no cron) |
| Notes | Detail content loaded by JavaScript. No API (tested: `?_format=json` → 406). Kept for listing breadth. Playwright deferred. |

---

## Planned Sources

### P2 — Nightlife Venues (22 listed)

**Chamonix Centre:**
- L'Alibi, Le Chamonix, Bar du Moulin, Mix Bar, Le Shack!, Maison des Artistes, Bar d'Up, Moö, French Blvd, Stories, Couleur Café, Beer O'Clock, Synge&Co, South bar, ChaChaCha, Amnesia, Le Garage

**Les Houches area:**
- The Wine Factory, Café de la Gare, Les Copains d'Abord

### P3 — Cultural Venues

- Cinéma Vox, Cinébus, Musée Alpin (closed until Q2 2026), Musée des Cristaux, Glaciorium, Temple de la Nature, Musée de l'Alpinisme, Musée Montagnard, Bibliothèque municipale, Bibliothèque des Pèlerins

### P4 — Hotel Event Calendars

- Alpina Eclectic Hotel, Lykke Hôtel & Spa, RockyPop, Le Prieuré, Hôtel Mont Blanc, Heliopic Hotel & Spa, Refuge des Aiglons, Bigsky, Excelsior Chamonix Hôtel & Spa, Park Hôtel Suisse, Hôtel de l'Arve, Le Morgane, Le Faucigny

---

## Ingestion Pipeline

Source -> Fetch -> Parse -> Normalize -> Validate -> Dedupe -> Merge -> Export JSON

| Step | Details |
|------|---------|
| Frequency | P0: every 6h (cron), P2-P4: TBD |
| Cron | chamonix-scraper — runs --no-detail for speed |
| Merge | chamonix.net is primary. chamonix.com events kept at unique URLs. Dedup by title+date+commune. |
| Output | data/events.json (overwritten each run) |
| Frontend | Serves events.json via static HTTP server on port 8080 |

## Scraper Health

| Scraper | Events | Descriptions | Images | Times | Venues | Status |
|---------|--------|-------------|--------|-------|--------|--------|
| chamonix_net.py | 12 | 12 | 12 | 8 | 12 | Healthy |
| chamonix_com.py | 20 | 0 | 19 | 0 | 0 | Listing only |

## Missing features

- Playwright scraper for chamonix.com detail pages (deferred)
- RSS/iCal export
- Individual venue website scrapers
- Multi-language support (FR/EN)
