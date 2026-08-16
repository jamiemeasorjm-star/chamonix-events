# REMEDIATION-BACKLOG.md — Current state → target harness + design

> Pulled from `docs/current-state-audit-2026-08-04.md`. Classified, sequenced, sized.
> **Docs-first, then sensors, then small code.** Each item names its quality-gate dependency.
> **Live-manual, updated 2026-08-07** — completed items checked off with commit refs;
> Aug 7 additions (own image placeholders + scraping improvements) in the final section.

## Phase 0 — Lock down docs & baseline (no code risk)
- [x] Commit + push repo → **recoverable baseline**. *Done: harness docs `ac25d1f`, then all remediation work merged to `main` by 2026-08-07. Only untracked leftovers are regenerable (`data/programme.pdf`, `*.db-*.bak`, `references/`, `scripts/web_foundation` symlink).*
- [x] Author the **harness docs** as the living manual (replaces stale docs/): `AGENTS.md`, `BUSINESS-RATIONALE.md`, `CITY-EVENTS-TEMPLATE.md`, `DESIGN-HARNESS.md`, `PIPELINE-SPEC.md`, `PROJECT-TRUTH.md`, `QUALITY-GATES.md`, `REMEDIATION-BACKLOG.md`, `RUNTIME-HARNESS.md`.
- [~] **chamonix-drop-report** activation — `drop_report.py` now wired into `storage.py`; `data/drop_report.jsonl` exists. *Not yet observed firing (empty)* — confirm it posts held-back events on a real drop.

## Phase 1 — Hardest data-truth fixes (pipeline)
- [~] **Canonical domain** (G4): `SITE_URL` is now a one-flip config `CHAMONIX_SITE_URL` (`777a751`). *Real domain drop-in still deferred* (placeholder stays, not live-advertised).
- [x] **Dual cinema → one source** (G2): cinema split onto its own `/cinema.html` (`607104f`/`9a7318d`) and `allocine_vox` now enriches `cinema_events` as the single source — legacy invisible rows cleaned; `vox_pdf` is the single writer (`2d5390d`/`24033b5`). 17/17 verified, build clean.
- [x] **Durable storage** (PIPELINE-SPEC §6): **FLIPPED ON** (`77b94d2`) — upsert-by-key + tombstone + protected `curated` sources, `DURABLE_DEFAULT=True`, live backup taken, 27/27 tests. *Revert = set `DURABLE_DEFAULT=False`.* Review follow-ups:
  - [x] Tombstone **expiry** wired into `clean_past.py` (`clean_tombstones`, `TOMBSTONE_MAX_AGE_DAYS`) so dead rows don't accumulate (`9568029`).
  - [x] Legacy `row_key IS NULL` backfill + durable first-run migration (`9568029`).
  - [~] Confirm `venue_name` normalization in the row key (only `title` currently accent/space-normalized).
  - [~] `get_events()` `absent_since IS NULL` filter — confirm behind the same opt-in flag.
- [x] **Cross-source EN/FR-aware dedup** (PIPELINE-SPEC §3): `EVENT_ALIASES` synonym table (UTMB etc.) + Unidivers venue-suffix collapse, via OpenCode (`4ebe6d3`, `e8a6f30`) + `CROSS_SOURCE_DEDUP_SPEC.md` + `test_dedup.py`. Duplicate cards collapse at build (in-memory, `dedupe_events`).
- [~] **Migrate ingestion to `wf` toolkit (staged)** — PIPELINE-SPEC §1:
  1. [x] Slice 1: `wf_chamonix_com.py` wf-based detail extractor (extract_url fast path → BrowserSession JS fallback), 8/8 real descriptions (`cabac4c`).
  2. [x] Slice 2: drop-in `wf_chamonix_com_detail.py` + parity gate `check_wf_detail_parity.py` + `wf_chamonix_com_detail.sh` wrapper (`265e874`, `65402bf`, `e01272b`) + **bulk-ingest path** (`4bd8d1a`, namespaced ids, durable upsert).
  3. [ ] **SWAP — NOT DONE**: old `chamonix_com_detail.py` is still the LIVE scraper; wf drop-in is **not** wired into `run_all.sh` / `chamonix-refresh.sh` / cron. Remaining operator step: verify parity gate PASS → swap → wire `wf_chamonix_com_detail.sh` into cron → only then retire the old scraper. *(Constraint: never delete the working scraper before parity is proven.)*

## Phase 2 — Sensors & gates (validation layer)
- [x] **`validate_content.py`** (coverage % venue/desc/image + live report, G1) and **`validate_build.py`** (orphaned-page/dead-UI/cinema/map-mappable/build-age, G2/G3/G5/G6) added read-only (`mode=ro`, exit-code bitmask) and wired into `chamonix-health-watchdog.sh` (`eb68064`).
- [~] Content+availability **watchdog** — availability + build validators now run on host cron; a full content-coverage watchdog push remains to be confirmed/wired.
- [ ] Schema validator on every published event (still open).

## Phase 3 — Clean-up (dead path / hygiene)
- [ ] Prune orphaned `events/*.html` (now **616 files**) — add prune to the render stage.
- [ ] Remove dead review UI/API/CLI + `review.html`; remove `run.sh`, `run_all.sh`, `scrapers/facebook_*.py`; remove `data/events.db`, `t26_verify.*`.
- [ ] De-god-`build.py` into render modules (PIPELINE-SPEC §8) — done behind gates.
- *(Done outside original plan, Aug 7)* fake nightlife listings removed via T-filter excluding curated recurring nightlife venue-ads (`8f7c5bd`).

## Phase 4 — Design/UX upgrade (aesthetics, behind G6)
- [ ] Tokens audit: confirm 5-token palette; migrate any off-token colours.
- [ ] Hero "What/When/Where + one CTA" upgrade; verify 5-second test on mobile.
- [ ] Posterless-film badge (honest label, G2) + cinema freshness messaging. *(Posterless content now shows a cinema watercolour placeholder — see §Aug-7.)*
- [ ] Map-first mode + list↔pin coupling on desktop (G3).
- [ ] Figma tokens/components sync via Dev Mode/MCP; visual-regression goldens established.

## Phase 5 — Repeatability (city/region platform)
- [ ] Extract `city.yaml` config; prove a second city can bootstrap from `CITY-EVENTS-TEMPLATE.md`.
- [ ] Write/reuse the skills (scrape, validate-build, aesthetic-review, cinema-ingest, city-bootstrap).

---

## Additions — 2026-08-07 (own image placeholders + scraping improvements)

These were changes made AFTER the audit (not in the original backlog) and are now part of the harness:

### A. Own image placeholders (category watercolours)
- [x] **9 watercolour category images** authored and committed to `placeholders/<cat>.jpg` (concert, exhibition, sport, market, family, theatre, nightlife, other, cinema; 1280x720 JPG — the live source the template references). PNG originals kept in `assets/categories/` (`1390c17`).
- [x] **Automatic fallback** in `index.html.template` `eventImg(e)` — applied to event-card, today-card, and modal: returns the category watercolour whenever `image_url` is empty, a `data:` URI, **or matches `GENERIC_IMG_RE`** (fallback-logo/placeholder/coming-soon/default-image/...). This fixes Unidivers events that shipped a generic fallback-logo in lieu of a real image (`78a0a95`).
- [x] Verified live: **61 events use watercolours, 30 use real photos**; category→image mapping correct; build clean (134 events); site healthy.
- [ ] Backfill note (future): if a source ships a generic placeholder that doesn't match `GENERIC_IMG_RE`, add its pattern to the regex in the template.

### B. Scraping improvements (ingestion quality)
- [x] **chamonix_com**: stop treating `/a-voir-a-faire/` (things-to-do) links as events — filters landing links out of event discovery (`183835c`).
- [x] **Categories, tiered → no more 'other' overspill**: shared `category_utils.py` — classify on TITLE first; if 'other', fall back to **low-noise** description phrases only (never generic incidental nouns like "marche"/"famille"/"jeu"); else stays 'other'. Keyword maps expanded (`a5e8877`, `fdccce3`).
- [x] **New sources**: mairie (`chamonix_fr`) + **Unidivers** event scrapers added; `chamonix_net` now paginated (`7649a02`).
- [x] **Cross-source dedup** improvements (see Phase 1) — `EVENT_ALIASES` + Unidivers venue-suffix collapse.
- [x] **wf-toolkit migration** slices 1+2 + bulk-ingest (see Phase 1) — recovers JS-rendered descriptions.
- [x] **Fake/invalid listings**: T-filter excludes curated recurring nightlife venue-ads (`8f7c5bd`).

---

## Sequencing rationale (docs → sensors → code)
Docs first (free, corrects operator ground truth), then sensors (turn the audit's "looks
complete" into measurable gates), then small code changes *behind* those gates so every refactor
is provably non-regressive. **Execution mechanism:** every code change is implemented by
**OpenCode in an isolated git worktree against a DB COPY** (per RUNTIME-HARNESS §4 + G7), with
Hermes independently verifying (re-run tests, read diff, confirm live DB untagged) and the
operator reviewing the diff before any merge — so the live site is never at risk during
refactors, including the staged **`wf` ingestion switch** and the **durable-storage flip**. The
`wf` switch is deliberately staged: new `wf`-backed scraper → parity behind G1 (recovers the
JS-rendered gap) → swap, never delete the old scraper first.

Highest-leverage items remaining: **wf swap + cron wiring → confirm drop-report fires → prune
orphaned `events/*.html` → Phase 3 dead-path cleanup → then Phase 4/5 design + repeatability.**
The durable-storage, cinema, dedup, and validator items from the original backlog are **done**.