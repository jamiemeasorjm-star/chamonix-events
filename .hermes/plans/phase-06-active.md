# T51+: Active / Future Work

**Status: 🔄 Active**

## Active Tickets

| Ticket | Description | Status | Priority | Notes |
|--------|------------|--------|----------|-------|
| T51 | Fix chamonix.com detail scraper URL patterns | 🔄 In progress | High | Sitemap uses `/animations-et-evenements-{commune}/` paths now |
| T52 | Publish enriched chamonix_com events | ⏳ Blocked | High | Blocked on T51 completing enrichment run |
| T53 | Fix AlloCiné source | ⏳ Planned | Medium | Syntax error, re-enable when fixed |

## Future Ideas

| Item | Priority | Notes |
|------|----------|-------|
| i18n for cinema films | Low | Titles/showtimes currently FR only |
| Venue section detail pages | Low | Static pages per venue |
| Event booking/ticket links | Low | Some events have billetweb links |
| Seasonal event curation | Low | Highlight winter/summer events |
| Mobile app wrapper | Very low | PWA sufficient for now |

## Known Issues

1. **chamonix.com detail scraper**: Sitemap URL structure changed — URL pattern fix deployed, enrichment currently running
2. **AlloCiné `active: false`**: Deferred syntax error (T02); not critical while vox_pdf provides cinema data
3. **110 events in admin vs 99 in healthz**: Build count mismatch — build.py uses a different query from http_server
4. **103 review items processed**: 57 approved, 46 rejected for chamonix_com — none published to events table (old approval bug)