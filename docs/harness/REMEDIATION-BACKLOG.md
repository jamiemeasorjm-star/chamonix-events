# REMEDIATION-BACKLOG.md — Current state → target harness + design

> Pulled from `docs/current-state-audit-2026-08-04.md`. Classified, sequenced, sized.
> **Docs-first, then sensors, then small code.** Each item names its quality-gate dependency.

## Phase 0 — Lock down docs & baseline (no code risk)
- [ ] Commit + push current repo (ahead 11, dirty `index.html`) → **recoverable baseline**.
- [ ] Archive or correct stale `docs/` (sources/mvp/schema/ingestion-flow/devops-handover/README);
      point operators to the skill + these harness docs as the living manual.
- [ ] Activate `chamonix-drop-report` (never fired) and confirm it posts held-back events.

## Phase 1 — Hardest data-truth fixes (pipeline)
- [ ] **Canonical domain** (G4): decide the real URL; make `SITE_URL` a config constant used
      identically in sitemap/OG/JSON-LD/robots. *(doc/domain decision → render change)*.
- [ ] **Dual cinema → one source** (G2): merge `allocine_vox` into `cinema_events`; stop
      publishing invisible category=Cinema events; poster+desc for every film or labelled badge.
- [ ] **Durable storage** (PIPELINE-SPEC §6): replace `DELETE-all-per-scrape` with upsert-by-key
      + tombstone/expiry + protected `curated` source so curated/community events persist.
      *(Option-B prototype done in worktree `durable-storage`, 13/13 tests pass, live-untouched.
      Before the production flip, close these review follow-ups:)*
      - Normalize `venue_name` in the row key (currently only title is accent/space-normalized).
      - Gate the `get_events()` `absent_since IS NULL` filter behind the same opt-in flag
        (today it's a safe no-op, but it's an unconditional behaviour change on merge).
      - Define one-time migration semantics for legacy `row_key IS NULL` rows (tombstone +
        translation-merge on first durable run).
      - Wire tombstone **expiry** into `clean_past` so dead rows don't accumulate.
- [ ] **Cross-source EN/FR-aware dedup** (PIPELINE-SPEC §3): fold "Valley/Vallée" etc. via
      synonym map so duplicate festival entries merge.
- [ ] **Migrate ingestion to the `wf` toolkit (staged)** — PIPELINE-SPEC §1:
      1. Land a `wf`-based scraper as a **new** module (e.g. chamonix_com detail via
         `BrowserSession`, chamonix_net via `extract_url`) in `web-foundation` venv.
      2. Verify **parity behind the gates** (G1 coverage ↑, no regressions, sample vs source).
      3. Swap the old ingestor only once the replacement is green — never delete the working
         scraper before parity is proven (web-foundation scope note: must not disrupt live site).

## Phase 2 — Sensors & gates (validation layer)
- [ ] `validate_content.py`: coverage % (venue/desc/image) + a live report (G1).
- [ ] `validate_build.py`: orphaned-page check, dead-UI check, cinema completeness, map mappable %
      (G2/G3/G5), build-age. Wire into cron (post-build) + CI (PR).
- [ ] Content+availability watchdog (promote current availability-only watchdog).
- [ ] Schema validator on every published event.

## Phase 3 — Clean-up (dead path / hygiene)
- [ ] Prune 425 orphaned `events/*.html` (add prune to render stage).
- [ ] Remove dead review UI/API/CLI + `review.html`; remove `run.sh`, `run_all.sh`,
      `scrapers/facebook_*.py`; remove `data/events.db`, `t26_verify.*`.
- [ ] De-god-`build.py` into render modules (PIPELINE-SPEC §8) — done behind gates.

## Phase 4 — Design/UX upgrade (aesthetics, behind G6)
- [ ] Tokens audit: confirm 5-token palette; migrate any off-token colours.
- [ ] Hero "What/When/Where + one CTA" upgrade; verify 5-second test on mobile.
- [ ] Posterless-film badge (honest label, G2) + cinema freshness messaging.
- [ ] Map-first mode + list↔pin coupling on desktop (G3).
- [ ] Figma tokens/components sync via Dev Mode/MCP; visual-regression goldens established.

## Phase 5 — Repeatability (city/region platform)
- [ ] Extract `city.yaml` config; prove a second city can bootstrap from
      CITY-EVENTS-TEMPLATE.md.
- [ ] Write/reuse the skills (scrape, validate-build, aesthetic-review, cinema-ingest,
      city-bootstrap).

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

Highest-leverage items to start: **commit + push baseline → canonical domain → durable-storage
flip (after the 4 review follow-ups) → single cinema source → content sensor (G1).**
