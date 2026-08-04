# T51+: Active / Future Work

**Status: ✅ Complete (53/53 tickets done)**

## Active Tickets

| Ticket | Description | Status | Notes |
|--------|------------|--------|-------|
| T51 | Fix chamonix.com detail scraper URL patterns | ✅ Complete | Sitemap URL pattern updated |
| T52 | Publish enriched chamonix_com events | ✅ Complete | 20 events published |
| T53 | Fix AlloCiné source | ✅ Complete | `active: true`, 14 films |

## Future Ideas

| Item | Priority | Notes |
|------|----------|-------|
| i18n for cinema films | Low | Titles/showtimes currently FR only |
| Venue section detail pages | Low | Static pages per venue |
| Event booking/ticket links | Low | Some events have billetweb links |
| Seasonal event curation | Low | Highlight winter/summer events |
| Mobile app wrapper | Very low | PWA sufficient for now |

## Known Issues

1. **Slug collision** — Events with same name diff dates overwrite files (116 events → 64 files). ~52 events masked but all linked slugs resolve to existing pages.
2. **Event count mismatch** — 127 DB vs 116 healthz (build.py dedupes differently from DB query)
3. **chamonix.shh.nz DNS unset** — Domain has no A/AAAA records (need 72.61.187.2 / 2a02:4780:79:3e25::1)
4. **Slug collision on detail pages** — Same-name events like "Afternoon Happy Hour" (weekly) all write to `afternoon-happy-hour.html`, only last one survives