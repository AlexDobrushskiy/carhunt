# olx_pt — OLX Portugal (Carros)

| | |
|---|---|
| wall | CloudFront WAF: 403 to every plain HTTP client (TLS/HTTP2 fingerprint), even with full browser headers |
| route | one plain-chrome tab on www.olx.pt; the site's own JSON API `/api/v1/offers/` fetched inside it |
| pace | ≥7 s between calls |
| phone | `/api/v1/offers/<id>/limited-phones/` needs a logged-in Bearer token → `Unsupported` here (login lives in browsers/contact) |
| messaging | site chat, logged in (OLX Group account, shared with standvirtual.com) |

## Query
`/api/v1/offers/?offset=(page-1)*40&limit=40&category_id=378&query=<model text>&filter_float_year:from&filter_float_price:to&filter_float_quilometros:to&owner_type=private` — codes in `codes.yaml`. No make/model filter is known: the model goes in as free text (`queries`), so rows can include other models (discover scopes them). Fuel and dealer-only are filtered on the rows (`combustivel` key, `business` flag). 40 organic rows/page plus promoted ones (`metadata.promoted` → `sponsored`); stops when `links.next` is gone.

## Rules (why)
- Plain HTTP is always 403 here; the tab-fetched API passes (11-01). A stray 400/404 right after opening a tab was seen once: retried once, then a block — an API 404 is never "ad gone".
- A search row is already the full offer (description, params, gallery): `ad()` serves rows from this session's searches with no extra call. A per-offer GET 403'd on 11-06 after a search pass; avoid it when the row is at hand.
- Cold `ad(url)`: the numeric id comes from the ad page (`"sku"`), then one API read.
- The API ignores `sort_by` (11-04): page the whole filtered set; `site_ref` = numeric offer id = the cursor. The URL token (`…-ID….html`) is `ad_id(url)` / `extra.url_id`.
- Phone reveal: logged out it worked on 11-01, then 400 "Disallowed for this user" from 11-04; logged in (Bearer = the `access_token` cookie) → 200. One at a time, ≥12 s apart. A 401 in a cloned logged-in profile = stale token, not a block: reseed the profile copies (11-05). `contact.phone == false` = chat only, no number.
- `partner.code == "standvirtual"` + `external_url` = a Standvirtual cross-post (`extra.mirror_of`): get its phone there (decoded offline, no login).
- 410 = ad gone; 200 + ad id = live (in-tab fetch, 11-04).

## Gaps
- Make field: the API has no make param; `Card.make`/`RawAd.make` stay empty (the title carries it).
- Fuel/dealer filters and the `:from`/`:to` bounds other than year:from, price:to, quilometros:to are not measured as API filters.
