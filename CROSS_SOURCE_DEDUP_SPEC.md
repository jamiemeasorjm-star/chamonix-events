CROSS-SOURCE DEDUP — PROBLEM SPEC & ACCEPTANCE CRITERIA
File to modify: scripts/dedup.py (and scripts/storage.py only if the public
API must change). Also may add a small test module scripts/test_dedup.py.

WHY THIS MATTERS
The chamonix-events DB now ingests from 4 overlapping sources
(chamonix_fr/mairie, chamonix_com, chamonix_net, unidivers). The SAME real
event frequently arrives from 2+ sources under slightly different titles, so
build.py's dedup (scripts/dedup.py -> dedupe_events) fails to collapse them and
the live site shows duplicate cards for one event. Current dedup uses an EXACT
match on normalize_title(title)+start_date, which only catches identical titles.

ROOT CAUSE OF THE MISMATCHES (concrete, from the live DB 2026-08-07):
1. UNIDIVERS APPENDS THE VENUE + LOCALITY TO THE TITLE. So:
     chamonix_fr: "58e Journées Minéralogiques"
     unidivers  : "58e Journées Minéralogiques Le Majestic Centre des Cong..."
   (same event, same date 2026-08-08) — exact match fails because unidivers has
   the extra trailing venue text.
   More pairs:
     "Fête des Guides aux Gaillands"  (chamonix_fr)
     "Fête des Guides aux Gaillands Site des Gaillands Chamonix-..." (unidivers)
     "Match de Hockey sur Glace Chamonix Vs Grenoble" (chamonix_fr)
     "Match de Hockey sur Glace Chamonix Vs Grenoble Patinoire..." (unidivers)
     "Soirée Indienne" (chamonix_fr)
     "Soirée Indienne Temple Protestant Chamonix-Mont-Blanc" (unidivers)
2. HTML ENTITIES not decoded: unidivers title has "d&rsquo;orgue" vs chamonix_fr
   "d'orgue" (Festival d'orgue de la vallée de Chamonix ... 2026-08-09 / -08-16).
3. Minor word/order variants (e.g. "...Visite guidée..." vs "...Visite guidées...").

GOAL
Collapse events that are the SAME real event (same start_date + same underlying
event name) into ONE card, preferring the most authoritative + complete version.
Preference order when merging a group: highest confidence, then most fields
filled, then source trust (chamonix_fr == chamonix_com == chamonix_net are
official/high; unidivers is aggregator/medium — prefer official), then
deterministic tie-break.

WHAT TO CHANGE
- HTML-decode entities (&rsquo; -> ', &amp; -> &, etc.) in the title before
  comparing. Use html.unescape.
- Normalize: lowercase, NFKD, strip diacritics, collapse whitespace, drop
  punctuation as today. ALSO strip a trailing "<VENUE> <LOCALITY>" suffix that
  Unidivers appends, so two titles that share a common EVENT-name prefix compare
  equal. A robust approach: strip known locality tokens (Chamonix-Mont-Blanc,
  Chamonix, Les Houches, Servoz, Vallorcine, Argentiere, Haute-Savoie) and strip
  a trailing venue-like substring; but do NOT over-match (e.g. don't merge
  "Sortie nature X" with "Sortie nature Y").
- SAFEST DESIGN (recommended): keep dedup_key = exact normalized match as the
  PRIMARY bucket. ADD a SECOND-STAGE fuzzy pass: after exact bucketing, for
  events on the same start_date that did NOT collide exactly, compare their
  normalized event-name (with venue/locality suffix stripped) using a token-set
  similarity (e.g. intersection-over-union >= 0.6, or "one title is a prefix of
  the other" after stripping venue). Merge them. This avoids aggressive
  over-merging.
- Preserve existing behavior for the normal case (identical titles still merge).

REQUIREMENTS / CONSTRAINTS
- Must NOT break the current self-tests in dedup.py __main__.
- Keep function signatures where possible (dedup_key, best_of, dedupe_events).
- Do NOT touch the DB schema or the durable upsert (source_id co-existence in
  the DB is FINE and intended — dedup happens at build time, in memory, in
  build.py line ~797 via get_storage().dedupe_events(events)).
- Do NOT modify build.py unless strictly necessary.
- Work ONLY inside this repo (scripts/).
- Run the pipeline to verify: ./venv/bin/python3.11 -m scripts.dedup  (self-test)
  and ./venv/bin/python3.11 build.py  (must succeed; event count should DROP vs
  current ~174 once duplicates collapse). Report before/after event counts.

DELIVERABLE
- Modified scripts/dedup.py (+ optional scripts/test_dedup.py with unit tests
  covering the concrete pairs above).
- A short summary of: what you changed, how dedup now behaves, before/after
  duplicate counts from a real build.py run, and any edge cases you did NOT fix.
