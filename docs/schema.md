# Core Data Schema (v1)

## Event

- id: string (uuid or slug)
- title: string
- description: string (markdown)
- start_date: ISO 8601
- end_date: ISO 8601 (nullable — single-day events)
- time: string (e.g. "20:00" or "19:00-23:00", nullable)
- venue_id: string (ref Venue)
- category: enum (concert, theatre, sport, market, exhibition, nightlife, family, other)
- commune: string (Chamonix, Argentiere, Les Houches, Servoz, etc.)
- source_id: string (ref Source)
- source_url: string
- image_url: string (nullable)
- price: string (nullable)
- status: enum (draft, pending_review, published, rejected)
- confidence: float (0.0–1.0)
- created_at: ISO 8601
- updated_at: ISO 8601

## Venue

- id: string (slug)
- name: string
- commune: string
- address: string
- latitude: float (nullable)
- longitude: float (nullable)
- url: string (nullable)
- phone: string (nullable)
- source_id: string (ref Source)

## Source

- id: string (slug)
- name: string
- type: enum (official, aggregator, venue, scraper)
- base_url: string
- trust_level: enum (high, medium, low)
- ingestion_cadence: string (e.g. "6h", "24h")
- active: boolean

## ReviewItem

- id: string (uuid)
- event_id: string (ref Event)
- reason: enum (low_confidence, duplicate, missing_data, parse_error)
- notes: string
- reviewed_by: string (nullable)
- reviewed_at: ISO 8601 (nullable)
- status: enum (open, approved, rejected)
- created_at: ISO 8601

## Data Flow

Source → Fetch → Parse → Normalize → Validate → Dedupe → Score → Upsert → Review queue → Publish → Export JSON
