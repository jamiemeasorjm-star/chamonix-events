WF-TOOLKIT MIGRATION — SLICE 2: DROP-IN DETAIL PIPELINE + PARITY GATE (STAGED)

Scope for OpenCode. This is the NON-DESTRUCTIVE build half of the migration.
IMPORTANT: Do NOT modify chamonix-refresh.sh, run_all.sh, chamonix_com_detail.py,
chamonix_com.py, storage.py, or build.py. Do NOT wire anything into any pipeline
YET — that wiring is done by the operator (me) AFTER verifying your output. Do NOT
delete or alter the existing working scraper (chamonix_com_detail.py must keep
running — the site stays live on it until the swap).

CONTEXT / GOAL
chamonix_com_detail.py (the LIVE scraper) loads existing "chamonix_com" events,
discovers event-detail URLs from the chamonix.com sitemap, fetches each detail with
PLAIN httpx, enriches, and writes back via storage.upsert_events_ungated("chamonix_com", ...).
Its weakness (historical bug): chamonix.com pages are JS-heavy, so plain httpx yields
EMPTY descriptions. Slice 1 already built `scripts/wf_chamonix_com.py` (read-only
wf extractor: extract_url fast path -> BrowserSession JS fallback; 8/8 URLs get real
descriptions). Your job now is the STAGED drop-in that uses wf for the same job, PLUS
a parity gate that proves wf >= old coverage, PLUS a runtime wrapper — all without
touching the live pipeline.

KEY RUN CONSTRAINTS (already verified working):
- wf (trafilatura + playwright) deps live ONLY in the web-foundation venv:
    /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python
- That venv CAN import the chamonix scripts.* modules when the repo is on sys.path:
    export PYTHONPATH=/docker/hermes-agent-2bpx/data/chamonix-events
    /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python -m scripts.<module>
- `scripts.web_foundation` is a local (UNCOMMITTED) symlink to the wf package, already
  present in the repo — use it for imports: `from scripts.web_foundation import extract_url`
  and `from scripts.web_foundation.browser import BrowserSession`.
- Reuse the pure helpers already in `scripts/wf_chamonix_com.py`: strip_front_matter,
  first_heading, extract_description, parse_french_dates, parse_event_time, classify_category,
  detect_commune, extract_address_line, extract_event. Do NOT rewrite them.

YOUR DELIVERABLES (create files in /docker/hermes-agent-2bpx/data/chamonix-events/scripts/):

1) `scripts/wf_chamonix_com_detail.py` — a NEW wf-BASED drop-in replacement for
   chamonix_com_detail.main()'s flow, with an identical write path.
   Flow (mirror chamonix_com_detail.main() exactly so data contracts match):
   a. Load existing chamonix_com events from storage (`get_storage().get_events(source_id='chamonix_com')`),
      same review_items fallback as the original if empty.
   b. Discover event URLs from the sitemap — REUSE the existing discovery functions by
      importing them from the existing module: `from scripts.chamonix_com_detail import
      discover_event_urls, get_event_urls_from_sitemap, get_sitemap_pages`. (Do NOT copy them.)
      Use httpx.Client() with the same USER_AGENT for discovery only.
   c. For each URL, extract via `from scripts.wf_chamonix_com import extract_event` (the
      slice-1 wf extractor, which already does fast-path + browser fallback + parsing).
   d. Enrich the existing loaded events with each extracted detail — reuse/import
      `enrich_events_from_details` from scripts.chamonix_com_detail (do NOT rewrite).
   e. Write back exactly like the original: `storage.upsert_events_ungated("chamonix_com", enriched)`
      UNLESS --dry-run given.
   CLI: `--dry-run` (print what would change, NO write), `--limit N` (only first N URLs),
   `--no-browser` (documented; pass through). Print a summary line with desc-coverage
   stats (how many events now have a real description) so parity is observable.
   MUST NOT be wired into any pipeline by you.

2) `scripts/check_wf_detail_parity.py` — a READ-ONLY parity gate.
   - Pick a sample of ~8-12 chamonix.com event-detail URLs (reuse the slugs from slice 1:
     fete-des-guides-2026, festival-d-orgue-de-la-vallee-de-chamonix-31eme-edition,
     festival-la-nuit-des-ours-2026, utmb-mont-blanc-r, chamonix-photo-festival,
     marche-de-chamonix, concert-avec-dub-inc, marche-des-houches, plus any more from
     get_sitemap_pages() you can add).
   - For each URL, run BOTH: (a) OLD httpx path — reproduce the old detail extract (you may
     import the old extract_detail from scripts.chamonix_com_detail) — and (b) NEW wf path —
     `extract_event` from wf_chamonix_com.
   - Compare description coverage: per-URL desc_len_old vs desc_len_wf, and a summary:
     count of URLs where wf desc >= old desc (parity ok) vs where wf regressed (wf < old).
   - Gate STOPS (exit 1) if ANY URL regresses (wf desc notably shorter than old), else PASS
     (exit 0). Print a table + "PARITY: PASS/FAIL".
   This is how the operator decides the swap is safe.

3) `scripts/wf_chamonix_com_detail.sh` — a runtime WRAPPER that runs the drop-in under the
   correct venv, so it can later be hooked into the cron. It must:
   - cd into /docker/hermes-agent-2bpx/data/chamonix-events
   - export PYTHONPATH=/docker/hermes-agent-2bpx/data/chamonix-events
   - exec /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python -m scripts.wf_chamonix_com_detail "$@"
   It does NOT call the pipeline by itself.

4) Unit tests `scripts/test_wf_chamonix_com_detail.py` for any new pure logic you add
   (e.g. a safe merge/enrich wrapper). At minimum test that importing the module works
   and that a sample extract_event returns a non-empty description for a known URL (use a
   try/except network guard so tests don't hard-fail offline).

RULES
- Do NOT touch: chamonix-refresh.sh, run_all.sh, chamonix_com.py, chamonix_com_detail.py,
  storage.py, build.py, sources.yaml, dedup.py. Only ADD the new files above.
- Do NOT upsert/write unless --dry-run is OFF; and you will NOT run it in write mode
  against the live DB (that's the operator's later step). Run ONLY --dry-run and the
  read-only parity gate during your own verification.
- Keep imports self-contained; reuse slice-1 + existing-module functions (import, don't
  duplicate).
- Run under the web-foundation venv with PYTHONPATH as specified.

VERIFY BEFORE YOU FINISH (report all output):
- `python -m scripts.wf_chamonix_com_detail --dry-run --limit 3` prints details, no DB change.
- `python -m scripts.check_wf_detail_parity` prints the table + PASS/FAIL.
- Confirm `git status` shows ONLY your new files + pre-existing programme.pdf (no edits to
  existing scrapers).

DELIVERABLE REPORT: files created; parity table + PASS/FAIL; dry-run summary; confirmation
that no existing file / pipeline was modified. Keep it brief.
