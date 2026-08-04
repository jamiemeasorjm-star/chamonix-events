# BUSINESS-RATIONALE.md — City/Region Events Master Brief

> The product/business layer you operate from. This is NOT a full business plan — it is
> the rationale that explains **why the harness is shaped the way it is**.

## Audiences (city/region event sites, in value order)

1. **Visitors** (trip of a week+): "what's on during my stay, in which commune, can I just look".
2. **Locals**: one place for fragmented sources (nightlife, pop-ups, small venues).
3. **Tourism/municipal partners**: want their events surfaced accurately to the right audience.
4. **Future**: commercial event promoters / media / affiliates (monetisation, below).

## Trust promise (what "correct / useful / safe" mean here)

- **Correct** = the event is real, its date/time/venue/description belong to *that* event,
  and its image matches it. Two events can never carry each other's description or poster.
- **Useful** = the calendar is complete enough to reliably answer "what's on" — a stalled or
  silently-thinning feed is *not* useful.
- **Safe** = no broken links, no fake canonical URLs, no posterless/presentationless films
  posing as real listings, no dead UI that implies a review process which no longer exists.

## Minimum production-trust bar (before any city site may call itself a "rolling events calendar")

1. One canonical source per domain (events / cinema / venues); no invisible or competing writers.
2. No published event with empty **title+date+venue**; description/venue gaps below a configurable %, and any gap is visibly labelled, not silently masked.
3. Cinema: every listed film has a **poster AND description**, or is explicitly labelled "details unavailable"; showtimes are fresh (not stale-week).
4. A **real, resolved canonical domain** consistent across sitemap/OG/JSON-LD/robots.
5. No orphaned pages served, no dead review UI on the live path.
6. Coverage + durability: a source stopping its listing is **detected and surfaced**, not silently destructive; curated events survive daily scrapes.
7. Sensors (not just raw counts) prove build freshness, content validity, and aesthetic no-regression on every deploy.

Below this bar a site is **demo/pilot** (fine to look at, must NOT be marketed as authoritative).

## Monetisation / side-hustle possibilities (high-level only — nothing live)

- **Referral/affiliate**: ticket/booking links (billetweb etc.) with referral codes on detail pages.
- **Sponsorship**: partner venues/municipalities pay for a featured/verified slot (must be visibly labelled, never corrupt listing order without disclosure).
- **Promoted events**: small paid placements with clear "Sponsored" treatment.
- **Future multi-city SaaS**: the harness + template is the product; cities subscribe to get their rolling calendar.
- **Why this matters for the harness**: monetisation only works if *trust* is real (audiences & partners must believe the listings are accurate). That trust is exactly what the QUALITY-GATES + sensors enforce. Trust is the asset; the harness protects the asset.

## Why the harness needs strong validation, coverage, and durability

- **Validation** because one bad source or one LLM batch can poison many listings (the T55 description bug is the canonical cautionary tale).
- **Coverage** because the product promise is "everything happening" — a source going quiet is a product failure, not a silent no-op.
- **Durability** because a rolling calendar's value compounds over time; DELETE-all-per-scrape means the "calendar" has no memory and no curated depth.

## The one-line rationale

> The harness exists so that **trust is engineered, not assumed**: a single canonical
> pipeline, a real quality gate, a coverage/durability layer, and a business-rationale doc
> that governs *why* each constraint exists — so every future edit is traceable to intent.
