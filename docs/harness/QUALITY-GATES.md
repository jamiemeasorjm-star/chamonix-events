# QUALITY-GATES.md — Hard gates before content/site changes ship

> A gate is a **blocking** check with an owner and an alert. Green = safe to ship.
> Default posture: **fail-closed** for content correctness; **fail-open** only for
> availability (never for data truth). All gate results flow to the operator by push.

## G1 — Event content gate (pre-publish)
- 100% of published events have non-empty `title`, `start_date`, `source_url`.
- ≥ configured % have non-empty `venue_name` and `description` (target ≥95%; any below is
  a GAP that is **visibly labelled on the card**, never silently masked).
- Any event missing the above is either blocked or tagged `under-verified`.

## G2 — Cinema gate (section "ready")
- Every listed film has **poster AND description**, OR is explicitly labelled
  "details unavailable" (`[VERIFIED]`-style badge), never a bare letter tile.
- Showtimes are **fresh**: `end_date >= today` for all listed films; if the block would be
  empty, surface an alert (don't silently vanish).
- Exactly **one** canonical cinema source (cinema_events); no invisible twin dataset.

## G3 — Map gate (section "useful", not just present)
- ≥1 venue with coords (else toggle auto-hides — current behaviour is correct).
- ≥ configured % of events resolve to a venue with coords (target ≥70%); below → alert.
- No marker rendered with empty payload; venue names are not the sole link (migrate to `venue_id` FK).

## G4 — SEO / canonical domain gate
- The canonical domain resolves (DNS + HTTP 2xx) and is **identical** in sitemap / OG /
  JSON-LD / robots.
- No "localhost"/placeholder/fake domain in served metadata.

## G5 — Clean site gate
- No orphaned `events/*.html` outside the current event set (prune check passes).
- No dead review UI / review API surfaced on the live path (review removed → remove UI).
- No stale test DB files (`events.db`, `t26_verify.*`) in `data/`.

## G6 — Aesthetic/UX gate (design changes)
- Hero communicates **What/When/Where** in a 5-second glance (telegraphic headline, date,
  primary CTA visible above the fold on mobile).
- Single dominant CTA per page; event card shows image, title, time, venue, category, CTA.
- Mobile sanity: no horizontal scroll, tap targets ≥ 44px, filters usable; visual-regression
  diff ≤ configured threshold vs goldens; light+dark both pass contrast.

## Gate owners & hooks
- Executed by: unit tests (`test_*`), a `validate_build.py` sensor, a `validate_content.py`
  content sensor, and CI on PR. Alerts to the operator chat on any trip.
- These are **sensors in the harness** (RUNTIME-HARNESS §2) invoked by cron/CI — not
  one-off manual reviews.
