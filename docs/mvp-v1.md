# MVP v1 — Scope

## Must Have

- [ ] Homepage feed: rolling list of events sorted by date
- [ ] Date range picker (start → end)
- [ ] Filters: category, commune, venue
- [ ] Event detail page (title, date, time, venue, description, source link)
- [ ] Venue page (list of events at that venue)
- [ ] Ingestion from 2–3 initial sources
- [ ] Review queue (flag low-confidence events for manual review)
- [ ] JSON export pipeline (events.json, venues.json, meta.json)

## Should Have

- [ ] About/trust page (transparency on sources)
- [ ] Basic search (title, venue name)
- [ ] "This week" / "This weekend" quick filters
- [ ] Responsive mobile layout

## Out of Scope (v1)

- User accounts / login
- Itinerary builder
- Payment processing
- Full CMS
- iCal/ICS export
- Map view
- Notifications

## Phased Roadmap

| Phase | Focus | Output |
|---|---|---|
| P1 | Data model + source policy | Schema docs, source list, trust levels |
| P2 | Ingestion + export | Python scripts, JSON pipeline |
| P3 | Frontend | Public website wired to JSON |
| P4 | Review/Admin UI | Review queue workflow |
| P5 | Launch + metrics | Deploy, monitor, iterate |
