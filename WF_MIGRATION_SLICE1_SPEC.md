WF-TOOLKIT MIGRATION — FIRST SLICE (STAGED, NON-DISRUPTIVE)
Scope for OpenCode. Do NOT wire anything into run_all.sh / chamonix-refresh.sh
or touch build.py / storage.py. This is a NEW module + a verifier ONLY.

CONTEXT
- chamonix-events repo: /docker/hermes-agent-2bpx/data/chamonix-events
- The `wf` toolkit (web-foundation) is the mandated extraction path. It is a SEPARATE
  repo at /docker/hermes-agent-2bpx/data/web-foundation, but I have symlinked its
  `web_foundation` package INTO this repo as `scripts/web_foundation` so it is
  importable from here.
- IMPORTANT RUN CONSTRAINT: the wf package needs trafilatura + playwright, which live
  ONLY in the web-foundation venv. So new wf-based code MUST run with:
      /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python  (NOT chamonix venv)
  and with the chamonix-events repo on sys.path so `scripts.*` imports resolve.
  Example:
      export PYTHONPATH=/docker/hermes-agent-2bpx/data/chamonix-events
      /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python -m scripts.wf_chamonix_com --url "..."
- The bug being fixed: the existing chamonix_com detail scraper (scripts/chamonix_com_detail.py)
  uses plain httpx and historically returns EMPTY descriptions for chamonix.com event
  pages (the site is Next.js/JS-heavy). `wf` fixes this via `BrowserSession`/`extract_url`.

YOUR DELIVERABLE (create these files in /docker/hermes-agent-2bpx/data/chamonix-events/scripts/):
1. `scripts/wf_chamonix_com.py` — a NEW wf-based chamonix.com event-detail scraper.
   - Input: one or more URL strings (--url, repeatable, or --urls-file <path> with one
     URL per line).
   - For each normalizes into the SAME Event fields the pipeline expects
     (title, description, start_date, end_date, time, venue_name, address, category,
     commune, source_url, image_url, price, source_id='chamonix_com', confidence).
   - Extraction: use `from scripts.web_foundation import extract_url` for server-rendered
     pages (fast path). If extract_url yields no/empty description, fall back to
     `BrowserSession` (JS render) to get the content. Parse the returned content (marked
     up in the `markdown` field of the Extraction object) to populate fields. You may use
     BeautifulSoup on the raw HTML if you need, but the wf extraction is primary.
   - Must be runnable as `python -m scripts.wf_chamonix_com --url "..." --dry-run`.
   - DO NOT call storage / upsert. Print the parsed event dict (JSON) in --dry-run mode.
2. `scripts/check_wf_parity.py` — a verifier (NOT a scraper).
   - Reads a sample of chamonix.com event-detail URLs (you may hardcode ~8 known-good
     ones from the sitemap — e.g. fete-des-guides-2026, brocante-vintage,
     festival-d-orgue-de-la-vallee-de-chamonix-31eme-edition, festival-la-nuit-des-ours-2026,
     utmb-mont-blanc-r, and any others you can enumerate from the sitemap pages
     `https://www.chamonix.com/sitemap.xml?page=1..3`, matching `/agenda/evenements-et-manifestations/`).
   - For each URL: run wf extraction (via scripts.web_foundation), report per-URL success
     (>= some description length), avg description length, and flag any URL with empty
     description. This proves the wf path fixes the empty-description bug.
   - Print a compact summary table + an overall PASS/FAIL line.
3. Unit tests `scripts/test_wf_chamonix_com.py` for any pure helpers you write
   (e.g. a function that strips wf markdown boilterplate and extracts a description).

RULES
- Do NOT modify existing scrapers, storage.py, build.py, run_all.sh, or chamonix-refresh.sh.
- Do NOT upsert/write to any DB. Only read the web + print JSON/summaries.
- Keep it self-contained inside scripts/ (plus the symlinked scripts/web_foundation).
- Run everything under the web-foundation venv with PYTHONPATH set, as above. Verify your
  module imports and runs (--dry-run on 1-2 URLs) and that check_wf_parity.py runs and
  prints its summary.

DELIVERABLE REPORT: what files you created, the parity summary (how many URLs now yield
a real description vs the old empty-description problem), verification output, and any
URLs that still fail. Keep it brief.
