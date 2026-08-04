# RUNTIME-HARNESS.md — The designed outer harness

> Maps the modern pattern (Guides → Sensors → PEV) onto this project, and maps every
> current script/runnable to its harness role. This is the *target*; today's wiring is
> documented in PROJECT-TRUTH.md and REMEDIATION-BACKLOG.md.

## 1. Guides (feedforward)

| Guide | File | Provides |
|---|---|---|
| Agent context | `AGENTS.md` | role, rules, map |
| Config-as-truth | `sources.yaml` | active sources, publish rules |
| Living ops manual | Hermes skill `chamonix-events` | procedural pitfalls/playbooks |
| Rules files | `QUALITY-GATES.md`, `PIPELINE-SPEC.md`, `DESIGN-HARNESS.md`, `BUSINESS-RATIONALE.md` | constraints + rationale |
| CI gates | `.github/workflows/*` (repo exists) | run sensors on PR/push |

**Skills to create (repeatable playbooks):** `scrape-source`, `validate-build`,
`aesthetic-review`, `cinema-ingest`, `city-bootstrap`. Each is a short SKILL.md with
triggers, steps, pitfalls, verify. `scrape-source` and `city-bootstrap` **wrap the shared
`wf` web-foundation toolkit** for fetch + clean-extract (see PIPELINE-SPEC §1) rather than
raw requests.

**MCP / tooling:** add an MCP server for **Figma Dev Mode** (read design tokens/components
without touching backend), a **SQLite read** MCP so sensors can query canonical state
directly, and use the **`wf` toolkit** (`web-foundation`: `extract_url`, `BrowserSession`,
`wf extract|browser|shot`) for scraping + clean extraction + design screenshots. These are
read/aux; they must never gate production output except via defined quality gates.

## 2. Sensors (feedback)

| Type | Sensor | Watches |
|---|---|---|
| Unit tests | `test_vox_pdf.py` (exists) + more | parser/scraper correctness |
| Schema validator | JSON/DB schema check on every published event | required fields, type, dates |
| Content checks | venue/description/image coverage %, cinema poster/desc %, map mappable % | data quality |
| Coverage | per-source "last listed" diff | silent source loss / deletion |
| Durability | curated+protected source preservation check | DELETE-all regressions |
| Build-age | `/healthz` build_age | freshness (exists) |
| Aesthetic | visual-regression screenshots + WPT/mobile sanity | no design regression |
| Eval harness | aggregate: coverage + correctness + freshness + aesthetic into one score | deploy readiness |

Alerts (push-only, to operator chat): any gate trip, source-coverage loss, cinema empty,
build stale > threshold, domain/SEO inconsistency.

## 3. PEV loop (per change type)

**Pipeline/scraper change:** Plan (which stage, what source) → Execute (dry-run + upsert to
staging) → Verify (schema + coverage + dedupe + a real sample vs source page).
**Build change:** Plan → Execute (rebuild) → Verify (HTML diff, event count, cinema integrity, footer/meta).
**Design change:** Plan (DESIGN-HARNESS spec + refs) → Execute (tokens/components) → Verify
(visual regression + UX sanity + mobile).
**Config/domain/durability:** Planning-only first — write plan, get sign-off, then implement.

## 4. How cron / wrappers / supervisor / CI integrate

- **Canonical runner:** `chamonix-refresh.sh` (06:00). Keep it the single scheduler entry.
  Split its steps so each is independently verifiable and independently alerted.
- **Rebuild:** `chamonix-rebuild-only.sh` (14:00) stays as availability fail-safe, and must
  run the post-build quality sensors too.
- **Watchdog:** promote the availability watchdog to a **content+availability watchdog**
  (add coverage/quality checks, not just `/healthz`).
- **Drop-report:** activate (currently never fired) as the visible held-back feed.
- **CI (GitHub Actions):** on PR push, run unit tests + schema/content validators so code
  quality is gated before it ever reaches cron.
- **Supervisor:** unchanged mechanically; ensure the http_server is the only bind on 8090.

## 5. Script mapping (current → harness role)

| Script/runner | Current | Harness role |
|---|---|---|
| `chamonix-refresh.sh` | live pipeline | **CANONICAL** scheduler entry (keep, de-fragment) |
| `chamonix-rebuild-only.sh` | fail-safe | **CANONICAL** availability rebuild |
| `chamonix-health-watchdog.sh` | availability alert | promote → content+availability watchdog |
| `chamonix-drop-report.sh` + `drop_report.py` | built, unused | activate; canonical held-back feed |
| `build.py` | god-function | **REFACTOR into stages** (render module) |
| `storage.py` | canonical DB layer | **KEEP**; fix DELETE-all (durability) |
| `vox_pdf.py` | cinema PDF | canonical cinema writer (merge w/ allocine) |
| `allocine_vox.py` | invisible events | **REFACTOR**: write to cinema_events (one source) |
| `chamonix_net/com/detail` | scrapers | canonical ingestion modules (**migrate fetch to `wf`**) |
| `nightlife.py` | scraper | canonical ingestion (tune exclusions) |
| `translate_job.py` | FR→EN | canonical enrichment (per-item desc verified) |
| `enrich_venue_commune.py`, `enrich_missing_addresses.py` | manual helpers | fold into enrichment stage (run each pipeline) |
| `clean_past.py` | purge | fold into expiry/tombstone logic |
| `cultural_venues.py`, `curate_venues.py`, `geocode_venues.py`, `update_venues_json.py` | manual | walk in to enrichment/venues stage |
| `review_cli.py`, review API in http_server, `review.html` | dead (review removed) | **REMOVE** |
| `run.sh`, `run_all.sh` | unwired runners | **REMOVE** |
| `scrapers/facebook_*.py` | legacy | **REMOVE** (not in pipeline) |
| `dedup.py` | superseded by storage | consolidate into one dedupe module |
| `data/events.db`, `data/t26_verify.*` | stale test files | **REMOVE** (briefing already repointed) |
