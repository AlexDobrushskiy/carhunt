# milanuncios_com — milanuncios.com (Spain)

| | |
|---|---|
| wall | Imperva ABP (`reese84`); curl gets "Pardon Our Interruption", any real Chrome passes on the first load |
| route | plain-chrome: one tab on the home page, then same-origin fetches of the pages; data in `window.__INITIAL_PROPS__` |
| pace | ≥8 s between loads, ≤60/run |
| phone | not in the page data; "Llamar" needs login + a Spanish IP, ≤3 per sticky session, ≤9/day → `Unsupported` here |
| messaging | logged in + Spanish IP, media on: "Mensaje" → "Escribir otro mensaje" → "Enviar" once; sender lives in contact |

## Query
`/<make>-de-segunda-mano/?s=<keyword>&orden=date&anod&anoh&kilometersTo&desde&hasta&fuels=electrico&vendedor=part|prof&pagina=N`
— codes in `codes.yaml` (make slugs, model keywords, params, fuel, seller, sort). No model filter exists: the model is a
title keyword, so rows can include other models (discover scopes). Makes without a category (`coches`) put the make in
the keyword. 41 rows/page, ≤200 pages per query. Ad ids grow with time (newest first = `orden=date`).

## Rules (why)
- Reads only through a real Chrome tab, one request per page (same-origin fetch, cookies included): plain HTTP gets the challenge.
- Phone endpoint 403 "Navegas desde fuera de España" to any non-Spanish IP, logged in or not; via a Spanish IP the 4th reveal in one session gets 403 → ≤3 per sticky session, then a new session; ≤9/day; take the slot before the click (a 403 counts).
- `contactMethods.phone` false = no "Llamar" button, messages only: `phone(reveal=True)` returns [] without touching the site.
- Messaging needs media on: with images/media blocked the click does nothing; a sent message favourites the ad.
- Liveness: a redirect from the ad to a list page (`?marca=…`) is a soft gone (removed at the 2nd signal ≥1 h later); `ad()` raises `Gone("soft: …")` on it.
- Dealer price with `includeTaxes: false` = net; private sales carry no VAT → `price_is_net` stays unset.
- Registration dates are year-only (`"YYYY"`).

## Gaps
- The ad page's container key for the ad object varies: the parser reads `adDetail` / `ad`, else the dict carrying the ad id.
- `desde` (price from) and `anoh` (year to) follow the site's URL scheme but are unverified; fuels other than `electrico` are unmapped (left unfiltered).
- Price sort: no known `orden` value → falls back to the site's default order.
- No reveal reader: phones come from the browsers + contact modules (logged-in Spanish-IP session).
