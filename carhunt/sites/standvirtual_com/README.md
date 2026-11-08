# standvirtual_com — Standvirtual (PT)

| | |
|---|---|
| wall | none on reads (CloudFront); reCAPTCHA v3 only on the site's "Mostrar VIN" button |
| route | plain HTTP; all data in Next.js `__NEXT_DATA__` (list: `urqlState` → `advertSearch`, ad: `advert`) |
| pace | ≥6 s between loads |
| phone | **decoded offline** from the ad page (`advert.phoneNumbers`); VIN too (`parametersDict.vin`) — no login, no reveal call |
| messaging | site chat, logged in (OLX Group account, shared with olx.pt); sender lives in contact |

## Query
`/carros/<make>/<model>?search[filter_enum_fuel_type]=electric&search[filter_float_first_registration_year:from]&search[filter_float_price:to]&search[filter_float_mileage:to]&search[private_business]=private|business&search[order]=created_at:desc&page=N` — codes in `codes.yaml` (filters, fuel, seller, sort, make/model slugs; VW = `vw`). 32 rows/page; stops at `totalCount`.

## Phone / VIN decode (`cipher.py`)
- Token `b64(ct+tag).<ver>.b64(iv)`, AES-GCM-256; key = PBKDF2-SHA256(hex(sha256(key_source)[:16]), site salt, 10 iterations, 10000 for ver `0`). key_source = `seller.uuid`, or `seller.standId` for dealer stands; VIN: the advert's numeric `id`.
- The salt is the site's own client constant, read from its JS bundles: the first ad with a token loads the page's `<script>` bundles (app chunks first, ≤60) and takes the literal next to `PBKDF2` that authenticates that token. Cached in `$CARHUNT_HOME/sites/standvirtual.com/cipher-salt.json`; re-read automatically when the cached one stops authenticating (site deploy). Override: `Plugin(salt=…)`.
- GCM authenticates, so a wrong salt/key never gives a wrong phone. A token that fails is dropped and counted in `extra.phones_undecoded` / `extra.vin_undecoded` with `extra.decode` saying why — never returned raw.

## Rules (why)
- `site_ref` = numeric advert id (the cursor: ids grow with new ads); `createdAt` is bumped by refreshes, never a cursor. The URL token (`…-ID….html`) is `ad_id(url)` / `extra.url_id`.
- Promoted rows (`vas.isPromoted`, `isPremiumTopAd`) are flagged `sponsored`: bumped out of date order, never a cursor.
- Never touch "Mostrar VIN" (reCAPTCHA v3, login-gated UI): the decoded VIN is the same value.
- Seller `type` PRIVATE with many active ads (`extra.seller_active_ads` ≥3) are often resellers: discover flags them.
- 410 = ad gone; 200 + ad id = live.

## Gaps
- Fuel codes beyond `electric`, and sort by price, unverified (sort=price → `Unsupported`).
- If the decrypting module ever moves to a lazily loaded chunk (not in the page's script tags), discovery finds no salt: phones come back empty with `extra.decode`; pass `salt=` until fixed.
