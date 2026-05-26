# Ingestion Flow

## Pipeline

Source -> Fetch -> Parse -> Normalize -> Validate -> Dedupe -> Score -> Upsert -> Review Queue -> Publish -> Export JSON

## Steps

### 1. Fetch
- Download source data (HTTP request, RSS, API call, HTML scrape)
- Cache raw response for debugging
- Handle HTTP errors, rate limits, timeouts

### 2. Parse
- Extract structured fields from each source format (HTML, JSON, RSS, iCal)
- Map to internal schema
- Flag parse failures for review

### 3. Normalize
- Standardize dates to ISO 8601
- Clean text (strip HTML, normalize whitespace)
- Map categories to enum values
- Geocode venue addresses if missing

### 4. Validate
- Required fields: title, start_date, source_url
- Date sanity checks (not in distant past/future)
- No obviously invalid data

### 5. Dedupe
- Match by: title + date + venue similarity
- On match: keep higher-confidence source, merge descriptions
- Score 0-1 confidence based on source trust + parse quality

### 6. Score
- confidence = source_trust * parse_quality * completeness
- Sources: High=1.0, Medium=0.7, Low=0.4
- Below 0.6 => auto-flag for review

### 7. Upsert
- Insert new events, update existing
- Mark status as published (confidence >= 0.6) or pending_review (< 0.6)

### 8. Export
- Generate events.json, venues.json, meta.json
- Frontend reads these static files

## Frequency

- Official calendars: every 6h (cron)
- Venue sources: every 12h
- Aggregators: every 24h
