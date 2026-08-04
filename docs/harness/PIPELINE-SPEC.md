# PIPELINE-SPEC.md — Stage-based pipeline (implementable, repeatable across cities)

> The contract every city/region pipeline must implement. Stages are explicit, each has
> inputs, outputs, and a verification hook. This replaces the current god-`build.py`
> + DELETE-all model.

```
ingestion → normalization → deduplication → validation → confidence+publish
→ durable storage → enrichment → render → post-build validation → (sensors/alerts)
```

## 1. Ingestion
- One module per source: `chamonix_net.py`, `chamonix_com.py`, `nightlife.py`,
  `vox_pdf.py`, `allocine_vox.py` (→ cinema), `cultural_venues.py`, `curated.py` (protected).
- Input: source endpoint. Output: `list[dict]` of *raw* events (source-authored fields only).
- **Fetch + clean-extract is delegated to the shared `wf` toolkit**
  (`web-foundation` at `/docker/hermes-agent-2bpx/data/web-foundation`) — MITM-free,
  covers server-rendered AND JS-rendered pages:
  - Server-rendered / static pages (e.g. chamonix.net, nightlife pages):
    `extract_url(url)` or `wf extract <url> --json` (trafilatura / `--engine auto`).
  - JS-rendered / SPA / load-more pages (e.g. **chamonix.com detail** — the historical
    root of empty descriptions):
    `BrowserSession().get(url, wait_selector=…)` / `wf browser <url> --selector …`
    (Playwright Chromium).
  - Screenshots for visual checks: `wf shot <url> out.png`.
- The scraper module maps the extracted structure into canonical fields; it does **not**
  roll its own httpx/BS4 fetch logic.
- **wf specifics (from `web-scraping` skill):** activate the wf venv
  (`cd …/web-foundation && . .venv/bin/activate`) before running `wf` or importing
  `web_foundation` — the system Python lacks these packages. trafilatura 2.2:
  `extract_metadata()` returns a **Document object**, use attribute access; and
  `trafilatura.metadata` is a module, not a function. Empty extraction + bare site
  title usually = JS/login/anti-bot wall (render with `wf browser` before assuming a bug).
- Rules: fetch with timeout+retry+UA; log raw failures; never let one source crash the run
  (non-P0 continues; P0 aborts loudly).
- **Migration safety (web-foundation scope note):** wf is a separate project/venv. The
  migration of Chamonix scrapers onto it is staged and must not disrupt the live site —
  land a wf-based scraper as a new module, verify parity behind the quality gates, then
  swap, never delete the working scraper before the replacement is green (see
  REMEDIATION-BACKLOG § Phase 1 → Phase 2).
- **Executor:** the `wf` migration is implemented by **OpenCode in an isolated worktree**,
  per RUNTIME-HARNESS §4 — Hermes verifies parity behind G1, and the old ingestor is swapped
  only when the new one is green. Proven recoverable: the option-B spike recovered 2466 chars
  of description + venue for the JS-rendered chamonix.com case that the current pipeline drops.

## 2. Normalization
- Standardise: ISO dates, clean text, strip Drupal/category prefixes, map categories,
  safe unicode, single residence for accented names.
- Every normalizer must pass **every field** it extracts (the historical "normalize drops
  venue/address/phone/website" bug is forbidden).
- Output: canonical event dicts with a stable `source_id`, `start_date`, `end_date`, `time`.

## 3. Deduplication (cross-source, EN/FR-aware)
- Key: `normalize_title(title, locale_aware)|start_date|venue`.
- **EN/FR-aware:** fold "Vallée/Valley", "Argentière/Argentiere" via a locale synonym map so
  the same event from two sources merges (current bug: "Chamonix Valley/Vallée Classics"
  both shown).
- Winner: confidence → field-completeness → deterministic source priority (Tier1>Tier2>Tier3).
- Merge: keep highest-confidence description/image; do NOT merge two different events' fields.

## 4. Validation (schema + content) — hard gate, see QUALITY-GATES
- Required: title, start_date, source_url. Sanity: date not absurdly past/future.
- Content: venue+description presence (categorised as PASS/GAP/MISSING), image present+reachable.
- Output: per-event validation record; nothing below gate publishes.

## 5. Confidence + publish rules
- Compute `trust × parse_quality × completeness` (existing `scoring.py`) with per-source
  `min_publish_confidence` from `sources.yaml`.
- publish_rules: exclude_title_patterns + dedupe + confidence floor.
- Unlike T55 (publish-all), the floor is a **real gate** again — but via a **visible,
  push-reported** path (drop-report), never an invisible queue.

## 6. Durable storage (NO DELETE-all-per-scrape)
- **Upsert by key** (source_id + normalized title + start_date + venue), not
  `DELETE WHERE source_id=?` then insert.
- **Tombstone/expiry:** events the scraper no longer finds are marked `absent_since`
  (`tombstoned`), expired by date, or preserved; they are **not instantly destroyed**.
- **Protected sources:** `curated`, `manual_submission` are never touched by a scraper's
  upsert — the recommended way to persist hand-picked/community events.
- Every row carries created_at/updated_at/absent_since for coverage diffing.

## 7. Enrichment
- venue/commune derivation from address (`enrich_venue_commune`, `enrich_missing_addresses`)
  run **inside the pipeline each run** (not manual post-hoc that gets wiped).
- per-item FR→EN translation for long descriptions (short fields may batch) — the T55 rule.
- image/poster verification + local cache fallback.

## 8. Render
- Build: pages, JSON artefacts, sitemap, robots, per-event detail pages **with prune**
  (remove orphaned `events/*.html` not in the current set).
- SEO: one **real canonical domain** (config constant) used identically in sitemap/OG/JSON-LD/robots.
- Split the god-function: `render_events.py`, `render_cinema.py`, `render_venues.py`,
  `render_static.py`, `render_seo.py`, `snapshot.py`.

## 9. Post-build validation — see QUALITY-GATES
- content coverage, cinema completeness, map sanity, build-age, orphan-page-check,
  dead-UI-check, aesthetic regression.

## Repeatability
A new city = a `city.yaml` (sources + palette + imagery + domain) + the same modules.
CITY-EVENTS-TEMPLATE.md bootstraps it. Identical pipeline, different config.
