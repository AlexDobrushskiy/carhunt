# subito_it — Subito (IT)

| | |
|---|---|
| wall | Akamai + DataDome — not triggered by plain HTTP |
| route | plain HTTP, Chrome UA; list = `__NEXT_DATA__` (30 rows/page), ad = RSC flight stream (`self.__next_f.push`) |
| pace | ≥6 s between requests |
| phone | `reveal`: `GET /hades/v1/contacts/ads/<urn>` (what "Mostra numero" calls), no login; only when `advertiser.phone` is set |
| messaging | site chat "Contatta", logged in (SMS-verified account); sender lives in contact |

## Query
`/annunci-italia/vendita/auto/?cb=<brand>&fl=4&ys=<ymin>&pe=<pmax>&me=<km bucket>&advt=0|1&o=N` — codes in `codes.yaml`.
The list filters by brand only: rows are kept when their `/car` Modello `group_key` matches `codes.yaml` (else the
model name). A brand without a code is searched as text (`q=<make>`) and rows of other brands
are dropped. `me` is a 5 000 km bucket (`me=11` = up to 54 999 km): discover still filters on the exact km.
Stops at `totalPages`. A JSON search API (`hades.subito.it/v1/search/items?c=2&t=s&…&sort=datedesc`) also answers without login; unused.

## Rules (why)
- Phones come national ("02…", "347…"): stored as +39….
- Long bodies are an RSC text record (`"body":"$4a"` → `4a:T<hex byte length>,…`, UTF-8 bytes): resolved, never stored as the pointer.
- `/car` values: map by `label` (Marca/Modello/Versione), not `level` — the "Altro allestimento" placeholder trim comes with level 0 and would be read as the make.
- Rows whose `kind` is not `AdItem` (ads/promos) are skipped.
- Reveal takes a `phone` pace slot first; 404 = the seller hides the number.

## Gaps
- `ps` (price min) and `ye` (year max) follow the site's `pe`/`ys` pairs but are unverified; so are fuel codes other than BEV (`fl=4`).
- BYD's `cb=002831` comes from ad data (unverified as a filter).
- Sorts other than the default (newest first) raise `Unsupported`. No phone day-cap is known.
- Liveness: 410 = gone; no other gone marker is known.
