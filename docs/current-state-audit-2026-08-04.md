# Chamonix Events — Current-State Truth Extraction (Operator Audit)

**Date:** 2026-08-04 · **Author:** Hermes (agent) · **Mode:** inspection/documentation only — no code changes made.
**Target:** `/docker/hermes-agent-2bpx/data/chamonix-events/` (+ scheduler wiring in `/root/.hermes/scripts/` and Hermes cron).
**Confidence grading used:** `[VERIFIED]` = traced from code/DB/runtime; `[PARTIAL]` = partially evidenced; `[UNCERTAIN]` = cannot fully confirm; `[STALE]` = doc/code claims something no longer true.

This report describes **reality, not intention**. Where the code contradicts a document, both are recorded and the mismatch flagged. It is deliberately unforgiving; it is the basis for a redesign, not a defence of the current state.

---

## 1. Executive summary

The site is **visually polished but data-thin and architecturally inconsistent.** It is a ~9-month-old greenfield project (git log starts `433964b`, ticket system T01–T55) that has been driven by an accelerating, same-day, operator-in-the-loop ticket cycle (T55a–T55e all landed 2026-08-04). Each fix was reactive and narrowly scoped, producing **layered half-states, dead code, competing data paths, and documentation that no longer matches the implementation.**

Specifically:

- **Two parallel cinema data paths** produce the same 6 films twice under different models; one path (`allocine_vox`) is entirely *invisible* anywhere on the site (`[VERIFIED]`).
- **The "review queue is gone" but the entire review API, CLI, admin card, and review page are still wired and served** — dead but not removed `[VERIFIED]`.
- **Only ~54 of 60 DB events render; 425 stale event-page files exist on disk for 54 live events** — the build never prunes old pages `[VERIFIED]`.
- **The map is venue-centric and shows markers for only a subset of filtered events** (those whose `venue_name` matches one of 23 geocoded venues); ~half of events are unmappable `[VERIFIED]`.
- **Metrics that pretend to prove health do not prove correctness:** `/healthz` returns ok with `events:54, cinema:6` while 2 of 6 cinema films have **no poster and no description**, and several published events have **empty venue AND empty description** `[VERIFIED]`.
- **Three pipeline-runner scripts exist** (`run.sh` legacy, `run_all.sh` repo, `chamonix-refresh.sh` Hermes-cron) with conflicting step sets; only `chamonix-refresh.sh` is scheduled `[VERIFIED]`.
- **The canonical URL domain (`https://events.chamonix.app`) is hardcoded everywhere (sitemap, OG tags, robots) but the site is actually served at a Hostinger workspace path; the hardcoded domain has no documented working DNS** — a real SEO/trust landmine `[VERIFIED] / [PARTIAL]`.
- **Docs are stale across the board:** `sources.md` (2026-07-23) still lists allocine_vox and nightlife *disabled* and the review queue *active*; `mvp-v1.md`/`README` still describe the review pipeline; `devops-handover.md` (2026-05-26) describes a port-8080/JSON-canonical architecture that no longer exists.
- **A handful of claimed-complete tickets reference files that do not exist** (`cultural_venues_detail.py`, `nightlife_detail.py` marked ✅ in the plan). 
- **Not committed/pushed:** git is ahead of `origin/main` by 11 commits and `index.html` is dirty; the repo is **not** backed up to GitHub despite a configured remote `[VERIFIED]`.

The good news: the **design system and frontend interaction layer are genuinely high quality**, the **description cross-contamination bug (T55) is actually fixed in current code** (per-item translation + dual-field idempotency filter — verified in `translate_job.py`), the footer `NaNj` (H1) is fixed, and the cinema table-wipe bug (C1) is fixed with `INSERT OR IGNORE` + id-dedupe.

**Bottom line:** the frontend masks the backend's thinness. Operationally the site looks "complete" but is one stale-week away from empty cinema, has invisible sources, and carries confidence claims (confidence score, `/healthz`) that are not backed by any verification loop. It is a **demo-grade harness with a production-grade skin.**

---

## 2. What the product truly is today

- **What it claims to be** (`README.md`, `product-brief.md`): a rolling single source of truth for Chamonix valley events, aggregating official sources + cinema + nightlife, mobile-first, no ads, for visitors (week+ trips) and locals.
- **What it actually is:** a **static, server-rendered HTML SPA-ish site** (inline JS/CSS, JSON injected into template, no real API for the frontend) built by a Python pipeline from a SQLite DB that is **fully rewritten at each 06:00 cron run by scrapers**. It currently shows **54 events** (from 60 DB rows) from 4 sources + a 6-film cinema block. Nightlife (26 events) is the largest source. ~28 events link to a geocoded venue.
- **It is NOT a "canonical" events store:** every source's `upsert_events()` does `DELETE all rows for source THEN insert what's currently scraped`, so **nothing persists except what the scrapers find live at 06:00**. There is no durable curated layer, no historical record, no diffing. (Documented in the skill as T55d; `[VERIFIED]` from `storage.py`.)
- **Trust promise implied:** the `about.html` page and the "confidence" vocabulary imply a quality filter. In reality **the filter now publishes everything** (confidence floor 0.0) — the only actual gates are regex title-blocking and a same-title dedupe.

---

## 3. Current runtime architecture

```
              HOST (VPS)                          CONTAINER bind-mount, same filesystem
┌────────────────────────────────────────────┐
│ Hermes cron (this session)                 │
│  chamonix-daily-refresh 06:00  ──► chamonix-refresh.sh (6 steps, no_agent, delivers to a TG chat)
│  chamonix-midday-rebuild  14:00  ──► chamonix-rebuild-only.sh (build.py only)
│  chamonix-health-watchdog every 6h ──► chamonix-health-watchdog.sh (alerts Ops chat)
│  chamonix-drop-report     06:10  ──► chamonix-drop-report.sh (NEVER RUN yet)
│  good-morning-stoic briefing reads chamonix.db (repointed 08-03, was events.db)
└──────────────┬─────────────────────────────┘
               ▼ executes scripts in:
   /docker/hermes-agent-2bpx/data/chamonix-events/
       venv/bin/python3  (or fallback /usr/bin/python3)
       build.py, scripts/*.py, data/chamonix.db (SQLite canonical)
               │
               ▼ writes static HTML + JSON artefacts
   index.html, about.html, review.html, submit.html, privacy.html,
   events/<slug>.html (425 files), sitemap.xml, robots.txt,
   data/events.json, data/cinema_events.json, data/builds/*.html
               │
               ▼ served by
   supervisor: chamonix-static → python scripts/http_server.py :8090
       └─► nginx :8095 (container conf chamonix-events.conf) 
            └─► host-nginx /events/ prefix proxy (strips prefix, re-added in http_server)
```

**Execution path (the live one), `chamonix-refresh.sh`:**
1. `chamonix_net --no-detail` (P0, fatal if fails)
2. `chamonix_com`, `allocine_vox`, `chamonix_com_detail` (P1, non-fatal)
3. `nightlife` (P1, non-fatal)
4. `clean_past.py` on events + cinema (P1)
5. `vox_pdf.py` (P0, fatal if fails)
6. `build.py` (always runs — "so a partial failure still produces a build")
7. `translate_job.py` (180s timeout, non-fatal)
8. `chamonix-health-check.py` (external, `/docker/hermes-agent-2bpx/data/scripts/`)
9. nginx conf re-apply

**Canonical truth location:** `data/chamonix.db` (SQLite). JSON files and HTML are **derived artefacts** whose *canonicality is a lie the docs tell* — they are outputs, and the HTML is what users actually consume.

---

## 4. Current harness and operating structure

The harness is **implicit and fragmented**, not one designed system. Five distinct "layers" act as the harness:

1. **Hermes cron jobs (the real scheduler)** — 4 Chamonix jobs in this session's cron (refresh 06:00, rebuild 14:00, watchdog every 6h to Ops, drop-report 06:10 never-run). `[VERIFIED]`
2. **Shell wrappers** in `/root/.hermes/scripts/` (refresh, rebuild-only, watchdog, drop-report).
3. **Repo-local runner scripts** that are *orphaned*: `run.sh` (2-step legacy) and `run_all.sh` (5-step, logs to the same file as refresh, uses `/usr/bin/python3`) — **neither is scheduled**; they are traps / competing truth. `[VERIFIED]`
4. **Governance gate** `scripts/gate.py` (git pre-commit: R1/R2 classification) + Hermes middleware `governance-hook` that routes every edit under `chamonix-events/` to `self-heal-fix`.
5. **Supervisor** for the HTTP server (`chamonix-static`, port 8090), auto-restart.

**What triggers what:** only the 06:00 refresh and 14:00 rebuild are real triggers. Watchdog passively alerts. Everything else is manual/reactive.

**Coupling / tight spots:**
- `build.py` does *too much*: reads DB, dedups, filters cinema, builds venues, injects template, writes 4 static pages, snapshots, writes JSON artefacts, writes metadata, generates event pages + sitemap + robots. A failure anywhere partially degrades many outputs.
- Scrapers depend on DB path resolution that has two hardcoded candidate paths (one dead).
- `http_server` late-imports `scripts.storage`/`scripts.sources`; stale bytecode requires a supervisor restart after storage edits (documented pitfall).
- **Silent-failure points:** `upsert_events` uses `INSERT OR IGNORE` — a colliding id is silently skipped; non-P0 scraper failures "continue"; translate times out silently; build "fails open" (keeps last good HTML) — good for availability, bad for staleness.

---

## 5. Governing documentation and business artifacts

| Path | Type | Active? | Reflects reality? | Role |
|---|---|---|---|---|
| `docs/product-brief.md` | Product brief | Historical | Partially — still the vision, but "review queue catches wrong events" is now false | Vision |
| `docs/mvp-v1.md` | Scope/status (2026-07-23) | Stale | **No** — claims 82 events, review pipeline, Port 8080-era | Fictional status |
| `docs/sources.md` (2026-07-23) | Source registry | **STALE** | **No** — lists allocine_vox & nightlife *disabled*, review queue *active*; reality is the reverse | Now misleading |
| `docs/schema.md` | Data model | Stale | Mostly — but omits `venue_name/address`, per-lang cols, publish_rules | Reference |
| `docs/ingestion-flow.md` | Pipeline doc | **STALE** | **No** — describes review-queue gate that was removed (T55) | Misleading |
| `docs/devops-handover.md` (2026-05-26) | Handover | **Historical/dead** | **No** — port 8080, `events.json` canonical, `/chamonix/` path | Should be archived |
| `docs/audit-2026-08-03.md` | Audit | Recent | Yes (its findings) but its C1/C2/H1/H2 are fixed now | Audit record |
| `.hermes/plans/*.md` | Ticket tracker | Mixed | Partly — phase-06 known-issues are honest (slug collisions, DNS); phase-04 claims files that don't exist | Tracker |
| `README.md` | Overview | Stale | **No** — claims review pipeline, "74 published", PWA, iCal live | Misleading |
| Skill `chamonix-events` (in `~/.hermes/skills/`) | **De-facto living ops manual** | Active | **Mostly yes** — this is the only doc kept current with T55a–e | Real harness doc |
| `sources.yaml` | Config-as-truth | Active | Yes | The actual publish gate |

**Key finding:** the only documentation that tracks reality is the **Hermes skill** (`SKILL.md`), which is effectively the operating manual. The in-repo `docs/` directory is largely stale fiction. There is **no business plan beyond the 894-byte product brief**, no monetization/strategy doc, no publication policy doc, no handover newer than 2026-05-26.

---

## 6. Business/product rationale currently encoded

- **Audience** (product-brief): visitors (week+) + locals. In practice the frontend is built for a general web visitor, no local-specific (e.g. "what's on tonight near me") affordances.
- **Trust promise:** "one place to see all events", "review catches wrong events". **Violated** — review removed, everything publishes, confidence is not used for gating.
- **"Useful/correct"**: the brief implies *coverage + accuracy*. Current system optimizes for *looking complete* over *being verified*.
- **Monetizable/business-usable behaviors implied:** none explicitly (brief says "not monetised in v1"), but the trajectory (trust page, cinema with posters, iCal, sitemap/SEO, structured data JSON-LD, PWA) implies an intent to become a **rankable, embeddable, referral/revenue-capable events product**. The SEO artifacts (sitemap, OG tags, JSON-LD) only work if the domain is real — which it isn't.
- **Quality bar implied by artifacts:** high (About/trust page, methodology, confidence ladder). **Not met by data** (empty venue/description rows published silently).
- **Where implementation violates intent:** invisible allocine cinema; empty-description events; hardcoded fake domain; events the scraper stops finding silently vanish (no coverage reporting).

---

## 7. Script and automation inventory

See **Table A** (appendix). Highlights:
- **Active (scheduled):** `chamonix-refresh.sh` → scrapers + build + translate; `build.py`; `vox_pdf.py`; `allocine_vox.py` (writes invisible data); `nightlife.py`; `clean_past.py`; `translate_job.py`; `http_server.py`; `chamonix-health-watchdog.sh`.
- **Active (manual/one-off tools):** `enrich_venue_commune.py`, `enrich_missing_addresses.py`, `cultural_venues.py`, `geocode_venues.py`, `curate_venues.py`, `update_venues_json.py`, `drop_report.py`.
- **Dead / vestigial:** `review_cli.py`, `dedup.py` (superseded by storage.dedupe_events→dedup), the entire review API in `http_server`, `run.sh`, `run_all.sh` (unscheduled), `chamonix_com_detail.py` (may be redundant with chamonix_com now), facebook scrapers (`scrapers/facebook_*.py` — legacy), `t26_verify.*` / `events.db` test leftovers.
- **Error surfacing:** scrapers print to log; non-P0 failures "continue"; translate swallows to silent; **only the watchdog alerts** and only on `/healthz` basics (build age / event count / status). No content-level verification.

---

## 8. True data-flow map

### Events
```
source site → [httpx+BS4 scrape] → dict → normalize() → dedupe(per-source, title+date+venue) 
→ upsert_events: DELETE source rows → publish_rules filter (regex-block, conf<0, dup) → INSERT OR IGNORE 
→ SQLite events → build.py load published, drop category=Cinema → cross-source dedupe (title+date) 
→ localized() → json.dumps → <script>var EVENTS=…</script> in index.html
   → events/<slug>.html (static pages) + sitemap.xml + robots.txt
```
**Failure points:** DELETE-before-scrape means a failed scrape = lost events (silent); `INSERT OR IGNORE` hides id collisions; cross-source dedup key is `normalized_title|date` so **EN/FR title variants of the same event do NOT merge** (e.g. "Chamonix Valley Classics" vs "Chamonix Vallée Classics" both present `[VERIFIED]`); no coverage diff when a source stops listing something.

### Cinema (TWO paths, see §12)
```
Path A: vox_pdf.py: PDF→parse→build_events→upsert_cinema (DELETE all + INSERT OR IGNORE) → cinema_events table → CINEMA_EVENTS → cinema section
Path B: allocine_vox.py: AlloCiné page→events( category=Cinema )→upsert_events('allocine_vox') → events table → build.py DROPS category=Cinema → ❌ invisible
```

### Image/poster
```
event image_url: from og:image (net) or allocine card / detail. 
cinema poster: local data/posters/* → POSTER_CACHE hardcoded → AlloCiné search → TMDB fallback.
No per-event image verification; broken/hotlink-blocked images render a letter placeholder (frontend) with no error captured.
```

### Geocoding / map
```
venues.json (26 curated, 23 coorded) → SQLite venues → VENUES + JS getVenueCoords().
Map markers ONLY for filtered events whose venue_name matches a coorded venue (28/60 events). 
Events have NO venue_id FK anywhere (`[VERIFIED]`: venue_id empty on all 60 rows) — venue linking is string-matched.
```

---

## 9. Frontend truth audit

- **Homepage renders from** `var EVENTS` (54), `var CINEMA_EVENTS` (6), `var VENUES` injected into `index.html.template`.
- **Event cards** built in JS from `#ev-grid`; guard for missing `image_url` → `.card-img-f` letter block; missing venue → hidden row; description truncated to 180 chars with expand.
- **Descriptions assigned** via `_l(e,'description')` (locale fallback `e['description_en']`→`e['description']`). The T55 per-item translation fix means the **current** English descriptions should be correctly paired — but **historical mis-pairs persist in the DB** if the cleanup (NULL all `description_en` + re-run) wasn't performed; the skill says it was a pitfall. `[VERIFIED for code fix; PARTIAL on data cleanliness]`
- **Masking behaviour (fake-working):**
  - Cinema 2/6 films have **no poster → renders `.no-img` first-letter tile** (looks intentional, is missing data).
  - Events with empty descriptions still render cards (description absent); empty-venue events are acceptable-looking but empty.
  - `index.html` build-time meta shows 14:00:03Z — footer is correct (no `NaNj`).
  - `https://events.chamonix.app` canonical/OG URLs are **bogus for the real host** — social shares/previews point at a domain that no one has confirmed resolves.

---

## 10. Map/location audit

- **Source of coords:** `venues.json` — 26 curated venues, **23 with lat/lng**; missing: Moon Tines, Amnesia, Le Garage `[VERIFIED]`.
- **Source of venue names:** events' `venue_name` (derived from scraper or `enrich_venue_commune.py`) — **13 of 60 events have NO venue_name**; 39 have no address `[VERIFIED]`.
- **Geocoding logic:** static curated coords (or `geocode_venues.py` Nominatim), NOT per-event geocoding. No fallback geocode at build time.
- **Empty-map behaviour:** `build.py` hides the Map toggle entirely if `count_venues_with_coords()==0` (`[VERIFIED]` — that guard exists, so a fully-empty map is hidden; a *partially populated* map is shown).
- **Markers:** one marker per unique venue among **filtered events** that resolves to a coorded venue. Popup shows *only the first event's* title/category/date for that venue (not a list).
- **Assessment:** `[VERIFIED]` the map is **venue-decorative and partial**: it is "real" (Leaflet + real coords) but **not a complete event map** — ~half of live events are unmappable, and clicking a marker reveals a single event, under-representing a venue with multiple events. It is genuinely useful only for orienting to venue locations, not for "where is this event".

---

## 11. Description / content-mix-up audit

- **Sources of descriptions:** scraped text (chamonix_net `.node__content` body with category-prefix stripping; chamonix_com detail enrichment; nightlife curated boilerplate). **No synthesized/hallucinated descriptions** — they are all scraped or curated. `[VERIFIED]`
- **The reported "mixed description" symptom:** root cause was the T55 **batch JSON translation trusting key order** → wrong `description_en` written to wrong event. **Fixed in current code** (`_translate_descriptions_per_item`, per-item, + idempotency filter requires BOTH `title_en` and `description_en`) `[VERIFIED]`.
- **One event inheriting another’s desc/image:** possible ONLY via the fixed batch bug (title matching itself can't remap), via cross-source dedup picking a different source's event for the same title (can swap which source's desc is shown), or via stale `description_en` left in DB from before the fix. `[PARTIAL]`
- **Weak assumptions in title matching:** dedup uses exact normalized-title equality; EN/FR variants don't match (see §8). Venue resolution uses a hardcoded 18-entry `VENUE_LOOKUP` + many `if "kw" in addr` rules — brittle, accented/English mismatches likely (e.g. "d'Argentière" vs "d Argentiere").

---

## 12. Cinema / poster / media audit

- **Sources (TWO, conflicting):** vox_pdf (PDF, → `cinema_events`) and allocine_vox (→ `events`, category=Cinema). `[VERIFIED]`
- **Freshness:** vox_pdf runs daily at 06:00 (despite `ingestion_cadence_hours:168`); the PDF is weekly. Cinema block shows films for the PDF's 7-day window; `build.py` expires films with `end_date < today`. **Result: all 6 current films end 2026-08-04 (today) — cinema will be empty tomorrow unless a fresh PDF is parsed.** `[VERIFIED]`
- **Poster logic:** local `data/posters/` (hash + slug) → hardcoded `POSTER_CACHE` → AlloCiné search → TMDB. **2 of 6 films resolve NO poster and NO description** (`LA MONTAGNE FAIT SON CINEMA`, `Int.—12 ans DE LA COMEDIE-FRANCAISE`).
- **Mismatch risk:** the same films exist in `allocine_vox` WITH posters and times, but are invisible (category=Cinema filtered from feed and not merged into cinema_events). **The poster-bearing data and the shown data are different datasets for the same films.** `[VERIFIED]`
- **Model mismatch:** cinema is forced into a separate `cinema_events` model with its own `showtimes_json`, duplicated from `events`. Two sources writing two shapes = the C1 fragility.
- **Trustworthy for production? NO** — 2 films posterless+descriptionless, section empties at week boundaries, and the richer AlloCiné data is discarded.

---

## 13. Error and failure-mode audit

- **Crash/script errors:** vox_pdf parser is very heuristic (column x-ranges, "FILMS" marker, month-boundary logic) — fragile to PDF layout changes; chamonix.com is JS-rendered (documented in devops-handover) so listing parse quality is declared low (`min_publish_confidence 0.2`).
- **Silent failures:** (`[VERIFIED]`)
  - `INSERT OR IGNORE` drops colliding rows without logging.
  - Non-P0 scraper failures only log "FAILED (exit N)"; content keeps last state.
  - A source that stops listing events → its events are `DELETE`d with **no coverage alert** (skill explicitly notes the drop-report does NOT catch this).
  - Translate timeouts+partial saves are logged as expected, not surfaced to operator.
  - `drop_report.jsonl`/`seen` are empty and the `chamonix-drop-report` cron **has never run** (`last_run_at: null`) — the "visible review feed" is not live.
- **Missing validation:** no schema validation on scraped events before publish; no check that every published event has non-empty required fields (title/date/venue/description); no image URL validity check.
- **Poison / stale-output:** a broken daytime scrape can leave **yesterday's HTML served with fresh timestamps** (build "fails open"), and `/healthz` reports `ok` regardless of content quality.
- **Proves success w/o correctness:** `/healthz` = build-age + raw counts. It can say `ok` while the site shows empty-description events and poster-less films.

---

## 14. Duplication / dead-path / drift audit

| Item | Type |
|---|---|
| `run.sh` (2-step), `run_all.sh` (5-step), `chamonix-refresh.sh` (6-step) | **Duplicated pipeline runners**, only refresh scheduled |
| `allocine_vox` → events (category Cinema) vs `vox_pdf` → cinema_events | **Competing "canonical" cinema datasets** |
| Review API/CLI/page/admin-card vs review stage removed | **Dead code still served** (endpoints return empty table) |
| `scrapers/facebook_*.py`, `facebook_targets.*` | **Legacy scraper** not in pipeline |
| `data/events.db` (0-byte), `data/t26_verify.db-shm/wal` | **Stale DB leftovers**; `events.db` is the exact trap that broke the 08-03 briefing |
| 425 `events/*.html` vs 54 live | **Orphaned static pages** (build never prunes) |
| `docs/` (stale) vs skill (current) | **Two documentation truths** |
| `index.html` tracked in git + dirty; ahead 11 | **Generated artefact in version control; changes uncommitted/unpushed** |
| `resolve_db_path` hardcodes dead `/opt/data/...` candidate | **Dead path reference** (doesn't exist) |
| `SITE_URL=events.chamonix.app` | **Fictional domain** in sitemap/OG/robots |

---

## 15. Documentation vs implementation mismatches (Table D)

| Claimed (doc/comment) | Actual | Mismatch | Risk |
|---|---|---|---|
| "Review queue catches wrong events" (brief/mvp/sources/schema/ingestion-flow) | Review removed T55; everything publishes | **STALE doc** | False operator expectations |
| allocine_vox & nightlife *disabled* (sources.md) | Both `active:true`, running daily | **Doc reversed** | Operator thinks cinema offline |
| "74 published, 26 venues, 14 films" (README) | 54 events, 26 venues, 6 cinema films | **Count drift** | Trust in README |
| Port 8080 / `events.json` canonical / `/chamonix/` (devops-handover) | Port 8090/8095, SQLite canonical, `/events/` | **Epoch drift** | Confused ops |
| T35 `cultural_venues_detail.py`, T36 `nightlife_detail.py` ✅ | Files do not exist | **Claimed-not-built** | Plan is fiction |
| `SITE_URL` https://events.chamonix.app | Site served at workspace Hostinger path | **Wrong canonical domain** | Broken SEO/shares |
| "100% images, 39 events" (audit 08-03) | Now 26/60 events lack images; exports partial | **Stale snapshot** | Over-confidence |

---

## 16. Documentation-to-harness alignment

- **Documents actually shaping runtime:** only `sources.yaml` (publish rules) and the **Hermes skill** (procedures). The skill is the de-facto governing doc.
- **Ignored documents:** everything in `docs/` except `audit-2026-08-03.md` informed past fixes. mvp/README/sources/schema/ingestion-flow are not consulted and are wrong.
- **Should be governing but isn't:** a publication policy / quality bar, a data-coverage SLA, a domain/SEO ownership doc, a proven business brief.
- **Business plan encoded in harness?** Essentially **no**. The tickets were feature-driven (T01–T55), not business-goal-driven. Nothing in code/automation encodes "trustworthy rolling events product"; the harness encodes "get events scraped and rendered fast".
- **What Hermes forgot/drifted on:** keeping `docs/` current, pruning dead code, removing the orphaned `run_all.sh`, resolving the dual cinema path, confirming the domain, and wiring the drop-report it built (never scheduled a run that fired).

---

## 17. Production-trust assessment

**Score: NOT production-trustworthy as a "source of truth" events product yet.**
Evidence: invisible source (allocine), cinema empties at week ends + 2 films are posterless, published events with empty venue+description, no pre-publish validation, no content verification, broken canonical domain, dead-but-served review UI, uncommitted/unpushed repo, and a scrape model where any source hiccup silently deletes events with no alert.

It is, however, **demo-/pilot-trustworthy**: it reliably serves a nice-looking, real-data events page that refreshes itself daily, with a working watchdog for availability. That is genuine value — it is just not the value the docs promise.

---

## 18. Top blockers (to becoming trustworthy)
1. **Resolve the canonical domain** — pick a real URL (events.chamonix.app or the Hostinger path) and make sitemap/OG/robots/JSON-LD consistent with it. (SEO + share integrity + "trust page" honesty).
2. **Collapse the dual cinema path** — decide one canonical cinema source; wire posters/times from allocine into the shown cinema block; stop publishing invisible allocine events.
3. **Add pre-publish content validation** + a coverage/age alert so empty-description/venue events and "source stopped listing X" are either blocked or surfaced, not silently shipped.
4. **Prune orphaned artifacts** (425 stale event pages, dead review UI, `run_all.sh`, test DBs) to stop them influencing reasoning and serving.
5. **Recompile `docs/`** to match reality (or archive stale ones and point to the skill as the living manual).
6. **Establish durable curated content** (a protected `curated` source) so events that outlive a scrape can persist — otherwise curated data vanishes at 06:00.
7. **Commit + push** the repo (11 commits ahead, dirty index.html) so there's a recoverable history.

---

## 19. Recommended harness redesign (future — separate from current truth)

Target: single pipeline with explicit stages + verification, business-rationale file as first-class input.

```
sources/
  chamonix_net / chamonix_com / allocine_cinema / vox_pdf / nightlife / curated
        │
ingest → normalize → validate(schema+sanity) → dedupe(cross-source, title+date+venue, EN/FR aware)
        │
publish_rules + confidence (computed, explained) → [quality gate: block empty-critical / low-conf] 
        │
       SQLite (events / cinema / venues / curated)      ← durable layer, no DELETE-all
        │
enrich (venue/commune, image verify, translate per-item)
        │
render (build pages + artefacts + sitemap/robots/OG real URL)
        │
validate-after-build (content check: N events, N with venue, N cinema w/ poster, build-age)
        ├───▶ alert to Ops chat if a quality gate trips (push, never pull)
schedule: single orchestrator (refresh) + separate rebuild + watchdog + drop/coverage report
business-governance docs/ (product-brief v2, publication policy, coverage SLA, domain ownership)
```

- **Separate stages into modules** (the user's 10-stage breakdown) instead of one `build.py` god-function.
- **Make validation a real stage** (not bootstrap the pipeline on confidence claims).
- **Stop DELETE-all-per-scrape.** Use upsert with a tombstone/expiry so a transient scrape failure doesn't self-destruct live data.
- **Single canonical cinema source.** One model, one writer.
- **Durability for curated events** via a protected source.
- **Coverage report** (what a source used to list that it no longer lists) so "silent deletion" becomes an alert, matching the user's push-only/preference.

---

## 20. Evidence appendix

See **Tables A–F** below. Key file/time evidence all cited inline above; canonical DB verified by direct SQLite queries at 14:29 UTC 2026-08-04; `/healthz` verified live (8090 + 8095 both `ok, events:54, cinema:6, build_age 0.56h`); supervisor `chamonix-static RUNNING (uptime 1d12h)`; git `ahead 11`, dirty `index.html`.

### TABLE A — Active scripts and automations
| path | purpose | trigger | input | output | active? | prod-facing? | failure mode | notes |
|---|---|---|---|---|---|---|---|---|
| `/root/.hermes/scripts/chamonix-refresh.sh` | 6-step refresh | cron 06:00 | sources | DB+HTML | ✅ | yes | P0 steps abort, P1 continue | THE live pipeline |
| `scripts/` scrapers (net/com/detail/nightlife/allocine_vox) | ingest | refresh | sites | events rows | ✅ | yes | non-fatal log | allocine writes invisible data |
| `scripts/vox_pdf.py` | cinema PDF | refresh | PDF | cinema_events | ✅ | yes | fragile parse, no poster fallback # | — |
| `build.py` | render chain | refresh+rebuild | SQLite | HTML/JSON/pages | ✅ | yes | partial | god-function |
| `scripts/translate_job.py` | FR→EN | refresh | events/cinema | *_en cols | ✅ | yes | timeout=partial save | per-item desc fix verified |
| `scripts/clean_past.py` | purge expired | refresh | events/cinema | deletes | ✅ | yes | silent | removal not reported |
| `scripts/http_server.py` | serve+healthz+dead review+admin | supervisor | files/DB | HTTP | ✅ | yes | port-conflict (doc pitfall) | review endpoints dead |
| `chamonix-health-watchdog.sh` | availability alert | cron every 6h | /healthz | Ops TG | ✅ | read | only basics | no content check |
| `chamonix-rebuild-only.sh` | build fail-safe | cron 14:00 | DB | HTML | ✅ | yes | fails open | — |
| `chamonix-drop-report.sh` (+`scripts/drop_report.py`) | held-back feed | cron 06:10 | drop_report.jsonl | TG | ⚠️ never run | read | none observed | built, not yet live |
| `run.sh` | legacy 2-step | manual | — | HTML | ❌ | — | — | superseded |
| `run_all.sh` | 5-step runner | manual | sources | log | ⚠️ orphaned | — | logs same file as refresh | unscheduled trap |
| `review_cli.py` / review API / review.html | review UI | manual | review_items | — | ❌ dead | — | — | review removed |
| `enrich_venue_commune.py`, `enrich_missing_addresses.py` | venue+commune | manual after scrape | events | venue cols | ✅ | yes | wiped on next scrape (T55d) | re-run each pipeline |
| `cultural_venues.py` | CSV ingest | manual | CSV | events | ✅ | yes | bypasses gate (ungated) | — |
| `geocode_venues.py`, `curate_venues.py`, `update_venues_json.py` | venues | manual | venues | coords | ✅ | yes | — | — |

### TABLE B — Data truth layers
| entity | source of truth | storage/output | consumer | confidence | issues |
|---|---|---|---|---|---|
| Events | live scrape (04:00-refresh) | SQLite events (60) | build→HTML | medium | DELETE-all wipes curated; empty-field rows; 54 render |
| Cinema | vox_pdf (6) | SQLite cinema_events | cinema section | **low** | 2 no poster+desc; empties at week end; allocine twin invisible |
| Venues | venues.json curated (26) | SQLite venues + JSON | map/VENUES | high | 3 no coords; events have no venue_id FK |
| JSON artefacts | derived | data/events.json etc | nginx/legacy | **low (derived)** | docs call "canonical" — false |
| Build snapshots | derived | data/builds/ (30) | rollback | high | only 1/day+rebuild |
| Review items | empty | review_items | dead API | n/a | obsolete |

### TABLE C — User-visible failures
| symptom | cause | where introduced | visible | severity | confidence |
|---|---|---|---|---|---|
| Cinema block thin/empty | week-boundary expiry + 2 films posterless | vox_pdf/build | cinema section | high | high |
| "No real map content" feel | only ~28/60 events mappable; venue-centric markers | venue_id absent, venue string-match | map | medium | high |
| Mixed English descriptions (historical) | batch-translate key-order bug (T55) | translate_job (pre-fix) | cards | **fixed in code**; data residue PARTIAL | med |
| Duplicate festival (Valley/Vallée) | dedup EN/FR title inequality | dedup.py | cards | medium | high |
| 425 orphaned event pages | build never prunes | generate_event_pages | /events/ | low(SEO) | high |
| Empty venue/description on some cards | no publish validation | scrapers/build | cards | medium | high |
| Broken OG/canonical share preview | fake SITE_URL domain | build.py | social/shares | medium | high |

### TABLE D — (see §15)
### TABLE E — Documentation artifacts (see §5)
### TABLE F — Priority repairs
| issue | impact | root area | fix type | urgency | dependency |
|---|---|---|---|---|---|
| Fictional canonical domain | SEO/share integrity | build.py SITE_URL | config/render | high | decide real URL |
| Dual cinema path + invisible allocine | section thin/empty, wasted data | vox_pdf/allocine/build | refactor | high | none |
| No content validation/coverage alert | empty rows ship; silent deletes | storage/refresh | new gate+alert | high | none |
| DELETE-all-per-scrape | curated data lost | storage.upsert_events | redesign durability | high | none |
| 425 orphan pages + dead review UI | clutter/dead path | build/http_server | prune | med | none |
| Stale docs/ | FALSE operator grounding | docs/ | recompile | med | none |
| git ahead 11 + dirty | no backup | repo hygiene | commit/push | med | none |
| drop-report never fired | review feed missing | cron | wire/verify | med | check 06:10 runs |
```
