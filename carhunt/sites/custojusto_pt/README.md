# custojusto_pt — CustoJusto (PT)

| | |
|---|---|
| wall | client-fingerprint 403: any plain HTTP client is blocked, the same IP passes in a real browser |
| route | one browser tab (lane) on www.custojusto.pt; pages read by same-origin fetch, data in Next.js `__NEXT_DATA__` |
| pace | ≥13 s between loads; stop at the first 403 |
| phone | none: `/api/ad/phone` POST 403s even from the ad page → `Unsupported` |
| messaging | "Enviar mensagem" contact form (one-way); the seller's reply opens a thread in the CJ inbox; login needed |

## Query
`/portugal/veiculos/carros-usados/<make>/<model>?o=N` — slugs in `codes.yaml` (VW = `vw`). 40 rows/page, newest first by default; stops on a short page. Price, year, fuel and seller type are filtered on the rows (`listItems[].price`, `params.regdate`, `params.fuel` label, `companyAd`); km is not on the rows. The promoted `galleryAds` strip ignores the path and is skipped.

## Rules (why)
- Plain HTTP at 6 s per ad + 3 s per phone POST → 403 after ~50 ads (11-03), still 403 hours later; a Playwright browser on the same IP loaded everything (11-04): the block is the HTTP client fingerprint. Browser reads at 12.5–13 s ran clean 11-04→11-07.
- km is shown only as a range (`base.mileage`, e.g. "40 000 - 49 999"): `RawAd.km` stays empty, `extra.km_range/km_min/km_max` carry it. Ask the seller for the exact km (cluster photo).
- Phone POST 403'd from the page in a real browser on 11-04, 11-05 and 11-06: contact by the form. Form messages are not lost: the reply arrived in the CJ inbox ~16 h later (11-05) — check the inbox for form-contacted cars.
- Login: only one profile held the CJ session; cloned profiles lacked it (11-04) → check login before a send.
- `params.whatsapp_nr` = `true` (same as the hidden phone) or a number (`RawAd.whatsapp`). `params.external_ad_id` = the dealer's stock ref (`extra.dealer_ref`, a dedupe key).
- Gone: redirect to the list with `?gone=<id>` (or 404/410, or `expiredAdData`); 200 + id = live (in-tab fetch, 11-04). 200 without page data = `Blocked`, never gone.

## Gaps
- The site's own filter params (`pe`/`ps` price buckets, `rs`/`re` year codes, `fu` fuel ids) are only partly known, so they are not used.
- Island districts (Açores/Madeira) show in `/portugal/` results; scope rules belong to discover.
