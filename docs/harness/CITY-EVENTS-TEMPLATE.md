# CITY-EVENTS-TEMPLATE.md — Bootstrap template for new city/region event sites

> Use this to stand up a new city/region site with **minimal changes**. Same harness, same
> pipeline, same design system; only config, sources, palette, imagery, and domain change.

## 0. Copy & rename
Copy `chamonix-events/` → `<city>-events/`. Replace the audit/truth docs pattern, not the code.

## 1. City config (`city.yaml`)
- `city.name`, `city.slug`, `city.domain` (REAL, resolved — G4), `city.commune_list`.
- `city.palette` (5 tokens), `city.brand`, `city.hero_imagery`.
- `sources:` list with `id/name/type/trust/cadence/active/min_publish_confidence/
  exclude_title_patterns` per source (mirror `sources.yaml`).
- `quality:` thresholds (venue/desc %, cinema %, map % — copy Chamonix defaults, tune per city).

## 2. Business rationale (adapt, don't rewrite)
- Copy `docs/harness/BUSINESS-RATIONALE.md`; adjust audience phrasing + market note. Keep the
  trust promise and minimum-production bar verbatim (they are the product contract).

## 3. Project truth
- Copy `docs/harness/PROJECT-TRUTH.md`; fill city name, sources table, domain, current counts
  from an initial baseline run. Mark demo vs production honestly.

## 4. Pipeline (`PIPELINE-SPEC.md` pattern, city sources)
- Implement the same 9 stages. Replace scraper modules only (city-specific source mappings).
- Keep: durable upsert, tombstone/expiry, protected `curated` source, EN/local-language-aware
  dedup (swap synonym map to the city's language pair), per-item description translation, prune.

## 5. Design (`DESIGN-HARNESS.md` pattern, city palette/imagery)
- Same components/tokens; only `city.yaml` palette + hero imagery change.
- Write `city-design.md` recording palette/imagery/brand decisions (so the next city is config).

## 6. Runtime harness
- Reuse: `AGENTS.md` (same rules), QUALITY-GATES (same gates), RUNTIME-HARNESS (same mapping).
- cron: refresh/rebuild/watchdog/drop-report with the same structure; CI runs the same sensors.

## 7. Go-live checklist
- [ ] Domain resolves + consistent across sitemap/OG/LD (G4)
- [ ] 3+ live sources ingesting; coverage report green (G1)
- [ ] Cinema/map sections pass G2/G3 (or explicitly parked with alert)
- [ ] No orphan pages / dead UI (G5)
- [ ] Aesthetic regression green on primary mobile+desktop (G6)
- [ ] docs/T project-truth current; git committed+pushed

## Deliverables for a new city (single PR-like change)
`city.yaml` + scraper deltas + palette/imagery + city-design.md + PROJECT-TRUTH.md — the
harness code and design system carry the rest.
