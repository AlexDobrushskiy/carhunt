# mobile_de — mobile.de (DE)

| | |
|---|---|
| wall | Akamai: curl, every Playwright-launched Chrome and `--headless` get "Zugriff verweigert" 403 |
| route | `plain-chrome` tab (Chrome launched plainly, attached after the first load); navigation (`goto`), ads live on suchen.mobile.de |
| data | Next.js RSC flight stream (`self.__next_f.push`): list + full ad in one load each |
| pace | ≥12 s, fresh profile every 20 loads, ≤60 loads/run, reads after 12:00 on messaging days |
| phone | in page data (`contact.phones[].uri`), privates too, no login, no reveal |
| messaging | "E-Mail schreiben" (`/checkout/core/<id>`), logged in only; sender lives in contact |

## Query
`/fahrzeuge/search.html?isSearchRequest=true&s=Car&vc=Car&ms=<make>;<model>;;&adLimitation=ONLY_FSBO_ADS|ONLY_DEALER_ADS&ft=ELECTRICITY&fr=<ymin>:<ymax>&ml=:<km>&p=<min>:<max>&cn=DE&sb=doc&od=down&pageNumber=N`.
Numeric make/model codes in `codes.yaml` (no slug fallback: a missing model raises `Unsupported`). Models without a
code use the model page `/auto/<slug>.html` with the same filters. Q4 e-tron sits under two model codes: both are
searched. 20 organic rows/page (+ ~4 paid rows on page 1); stops at `numResultsTotal`.

## Rules (why)
- Price = `price.grs.amount` (gross EUR, may be fractional → rounded). 10 prices were once stored ×100 (11-03); never fall back to `nt` (net).
- Paid rows `topOfPage`/`topInCategory` are `sponsored` (never a cursor); `eyecatcher` rows are organic.
- Ad ids come in two widths (9-digit old, 14-digit new): one numeric cursor per width, or new ads hide below the old maximum.
- Seller 7723851 = kleinanzeigen.de mirrors: e-mail only, `partner_url` = the original ad, their +49 30 92 10… numbers are call-tracking proxies (`extra.mirror`, `extra.phone_note`).
- Long descriptions come as an RSC text record (`"$77"` → `77:T<hex byte length>,…`): resolved from the stream.
- Burst limit is per browser profile (~25 fast loads 10-30, ~60 paced 11-04) → 12 s + fresh profile per 20; the home IP got 403 after 41 sweep loads (11-06) → ≤60/run and reads after the morning messaging window.
- Gone = 404 "Dieses Fahrzeug ist nicht verfügbar". The same phrase sits in every page's i18n bundle → only the `<title>` counts.

## Gaps
- Fuel codes other than `ELECTRICITY`, a make-only `ms=<make>;;;` and `sort=relevance` (= no sort params) were not exercised by the sources.
- `fresh_profile_every` / `read_after` are declared in site.yaml; the transport enforces neither yet.
