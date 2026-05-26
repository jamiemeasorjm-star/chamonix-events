# Sources — Chamonix Events Calendar

## Official Calendars (Tier 1 — High Trust)

| Source | Type | Notes |
|---|---|---|
| chamonix.com/evenements + /agenda | Official tourism site | Main events calendar |
| chamonix.net/english/events | English aggregator | Curated events |

## Venue-Based Sources (Tier 2 — Medium Trust)

### Nightlife — Bars & Clubs

**Chamonix Centre:**
- L'Alibi — Place de l'Église (bar)
- Le Chamonix — Rue de l'Hôtel de Ville (bar)
- Bar du Moulin (bar)
- Mix Bar (bar)
- Le Shack! (bar)
- Maison des Artistes — Chemin de la Tournette (bar)
- Bar d'Up (bar)
- Moö (bar)
- French Blvd (bar)
- Stories — craft brewery & bar
- Couleur Café (bar)
- Beer O'Clock — 74 Av. Ravanel le Rouge (bar, Mo-Su 17:00-01:00)
- Synge&Co — Place Edmond Desailloud (bar)
- South bar — Edan.io (Mo-Su 12:00-02:00)
- ChaChaCha — Av. Ravanel le Rouge (wine bar)
- **Amnesia** — well-known Chamonix nightclub (not in OSM — field verify)
- Le Garage — nightclub/bar (verify if active)

**Les Houches area:**
- The Wine Factory — Les Houches (bar)
- Café de la Gare — Les Houches (bar, Mo-Su 08:00-18:00)
- Les Copains d'Abord — Les Houches (bar)

### Cultural / Entertainment

- Cinéma Vox — 22 Cour du Bartavel, Chamonix (3 screens)
- Cinébus — Les Houches
- Musée Alpin — closed for renovations until Q2 2026
- Musée des Cristaux — Chamonix centre
- Glaciorium — Mer de Glace
- Temple de la Nature — Mer de Glace
- Musée de l'Alpinisme — Aiguille du Midi
- Musée Montagnard — Les Houches
- Bibliothèque municipale — Chamonix
- Bibliothèque des Pèlerins — Les Pèlerins

### Ski Resorts & Mountain Venues (host events)

- Brévent — lift-accessed events
- Flegère — summer/winter events
- Les Grands Montets — Argentière
- Le Tour / Balme
- Domaine des Planards
- La Flégère
- Plan de l'Aiguille — buvette (bar)

### Major Hotels (with bars/restaurants hosting events)

- Alpina Eclectic Hotel (4★) — alpinachamonix.com
- Lykke Hôtel & Spa (4★) — lykkechamonix.com
- RockyPop (3★, 148 rooms) — rockypop.com/chamonix
- Le Prieuré (4★) — prieurechamonix.com
- Hôtel Mont Blanc (5★)
- Heliopic Hotel & Spa (4★) — heliopic-hotel-spa.com
- Refuge des Aiglons — aiglons.com
- Bigsky (4★) — bigsky-hotel.com
- Excelsior Chamonix Hôtel & Spa (4★)
- Park Hôtel Suisse
- Hôtel de l'Arve
- Le Morgane
- Le Faucigny

## Trust Levels & Ingestion Approach

- **High** — Official websites: scrape structured pages directly
- **Medium** — Venue websites with calendars: scrape or RSS
- **Low** — Social media / informal: manual review first
- **Verify** — Not in OSM/known to exist: field-check before scraping

## Missing From OSM (Needs Field Verification)

The following well-known venues were NOT found in OpenStreetMap and need manual confirmation:
- Amnesia nightclub
- Le Garage nightclub/bar
- Any seasonal pop-up bars/clubs

## Ingestion Priority

P0: chamonix.com (official tourism calendar)
P1: chamonix.net events
P2: Top 10 nightlife venues with active social media/web presence
P3: Cultural venues (musée, cinema)
P4: Hotel event calendars
