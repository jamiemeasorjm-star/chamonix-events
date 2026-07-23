# T01–T09: Phase 1 — Pipeline & Runtime Stability

**Status: ✅ Complete** (committed in initial commits)

| Ticket | Description | Status | Notes |
|--------|------------|--------|-------|
| T01 | Scraper framework | ✅ | httpx + BeautifulSoup scrapers |
| T02 | chamonix.net scraper (EN) | ✅ | 10 events published |
| T03 | chamonix.com scraper (FR listing) | ✅ | Events route to review queue (low conf) |
| T04 | Le Vox cinema PDF parser | ✅ | 14 films |
| T05 | SQLite storage layer | ✅ | events, venues, review_items tables |
| T06 | Build pipeline (static site) | ✅ | build.py → index.html + detail pages |
| T07 | HTTP server | ✅ | systemd-supervised on port 8090 |
| T08 | CRON integration | ✅ | 6h/24h/168h cadences |
| T09 | AlloCiné scraper | 🟡 Disabled | `active: false` in sources.yaml |

## Remaining
- **T09**: Fix allocine_vox source syntax error and re-enable