# DESIGN-HARNESS.md — Aesthetic & UX system (repeatable for all city/region event sites)

> This is the **repeatable aesthetic harness**. Backend logic must never break because of a
> design change — design lives in tokens/components, data lives in the pipeline.

## Patterns from popular event sites (derived from well-known patterns of Eventbrite,
SXSW, Web Summit, Config-by-Figma, Tomorrowland, RA Guide; live re-verification recommended)
- **Hero (5-second "What/When/Where"):** Eventbrite & SXSW lead with a one-line value prop,
  a big date/place marker, and one dominant CTA. No clutter above the fold.
- **Info architecture:** agenda/schedule is king; filters (date → category → location) are
  persistent and forgiving; lineups/speakers are social proof; venue+map is a dedicated, clear block.
- **Visual identity:** tight 3–5 colour palettes, high text contrast, one display face + one
  text face, liberal whitespace; images carry the emotion.
- **UX:** mobile-first, scannable cards, one clear CTA, minimal friction to "see events"/
  "claim tickets". Tomorrowland/Config prove that a strong dark brand + bright accent can
  be gorgeous AND readable.

## What we adopt for Chamonix (and future cities)
- **Hero:** brand name + city vibe line, big date/place, one primary CTA ("See events"),
  quick filter chips (date/category/commune) immediately usable on mobile.
- **Event card** (existing design is strong — keep, standardise): image, title, time, venue,
  category tag, per-card CTA; explicit **under-verified** badge when G1 flags a gap.
- **Map + list:** default **list-first** (existing), with a **map-first toggle**; side-by-side
  on desktop for "map-first mode" — clicking a list card focuses its venue pin.
- **Cinema:** poster grid with showtimes; posterless films get an honest "details unavailable"
  badge (G2), never a bare letter tile.
- **Trust chrome:** real canonical domain, "Last updated", per-source methodology on the About
  page (existing) — these are the product's trust assets.

## What we avoid
- Wall-of-text heroes; 6+ accent colours; no CTA; posterless film tiles passed off as listings;
  fake canonical/social URLs; hiding data gaps behind pretty placeholders.

## Design system (target tokens — evolve current CSS vars, don't discard the good parts)
- **Colour:** 5 tokens max: `--bg`, `--surface`, `--text`, `--text2`, `--accent` (+ hover).
  Chamonix: alpine dark + gold accent (current). Future cities swap only the palette.
- **Type:** 1 display serif (Playfair) + 1 text sans (Inter) — current. Fixed scale (6 steps)
  driving `--rs`/`--rm`/`--rl` spacing rhythm.
- **Components (atomic):** `Chip` (filter), `EventCard`, `VenueChip`, `CinemaCard`, `MapPane`,
  `CTAPrimary`, `BadgeVerified/UnderVerified`, `Section`, `Hero`.
- **Tokens-first:** all values in `:root` CSS variables / JSON tokens; components reference
  tokens only (this is what lets a design change never touch backend logic).

## Figma integration strategy
1. **Represent designs as components + tokens** in Figma (auto-layout, variants, and a token
   layer: colour/space/type as Figma variables).
2. **Read, don't copy:** connect a **Figma Dev Mode / MCP server** so Hermes can read
   component specs + tokens directly. Backend receives only `tokens.json` + component markup.
   Design-verification screenshots come from the **`wf` toolkit** (`wf shot <url> out.png` /
   `BrowserSession`) for the G6 visual-regression diff.
3. **Sync tokens to code** via MCP/CLI/custom script → `tokens.json` → `:root{...}` in templates.
   A design change becomes: edit tokens → regenerate CSS → visual-regression verify (G6). No JS/DB changes.

## Repeatable aesthetic upgrade playbook
1. **Analyse** 3–5 comparable city/region event sites; extract what fits our audience.
2. **Propose** a textual design spec (hero, IA, colours, cards, cinema, map) grounded in
   BUSINESS-RATIONALE + QUALITY-GATES (never a purely cosmetic whim).
3. **Implement in Figma** with components/variants/tokens (auto-layout).
4. **Sync tokens/components** to code; apply with minimal backend impact (tokens/`tokens.json` only).
5. **Verify** (G6): visual regression vs goldens, mobile sanity, 5-second hero test,
   light+dark contrast; confirm no event/cinema/map data regression (G1–G3).
   **Screenshots come from the shared `wf` toolkit** (`wf shot <url> out.png`, full-page,
   or `BrowserSession().get(url).shot(…)`) — captured at fixed viewports (mobile + desktop)
   against golden images stored per design version; a `wf shot` diff is the visual-regression
   sensor for G6.

## Repeatable city/region aesthetic plan
Each city site gets a **`city.yaml`**: palette (5 tokens), imagery/hero art, brand name,
sources, domain, commune list. The same components + pipeline consume it. Documenting these
decisions (a `city-design.md` per city) means a future city = config + imagery, same harness.
