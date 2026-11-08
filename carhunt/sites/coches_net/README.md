# coches_net — coches.net (Spain)

| | |
|---|---|
| wall | Imperva ABP (`reese84`) via CloudFront; bot page "Ups! … eres un bot" (200) / "Pardon Our Interruption" (403) |
| route | gateway JSON `web.gw.coches.net` through a Spanish exit (`/search/listing`, `/details/<id>`); without one: plain HTTP pages, data in `window.__INITIAL_PROPS__` |
| pace | pages: ≤2 loads per rolling hour for every agent on the IP (pace kind `load`); gateway: ≥12 s apart, ≤60/run (kind `api`) |
| phone | dealers + most privates in the data; `phone(reveal=True)` = `GET /details/<id>/phone` via a Spanish IP (200 / 204 = hidden) |
| messaging | logged in, Spanish residential IP, non-Playwright browser, "Contactar" once → `contact-mail` 2xx; sender lives in contact |

## Query
Numeric ids only (`codes.yaml`: makes, models, fuel, seller, sort). One user model may span several site models
(`Q4 e-tron` = Q4 + Q4 Sportback). Page: `/segunda-mano/?MakeIds[i]&ModelIds[i]&Fueltype2List&MinYear&MaxYear&MaxKms&MinPrice&MaxPrice&st=1|2&fi&or&pg`
(35 rows). Gateway: `POST /search/listing {pagination{page,size:30}, sort{term,order}, filters{…}}`; `q.extra` = page
params on the page route, raw gateway filters (JSON values) on the gateway route.

## Rules (why)
- Never open coches.net in a Playwright-attached browser: Imperva sees CDP and flags every agent browser on the IP for hours. Reads are plain HTTP.
- Page loads ≤2 per rolling hour, shared by every agent: faster paging gets the bot page, via the ES proxy too. The plugin also refuses a 3rd page load per hour in-process.
- Contact and phone APIs 403 every non-Spanish IP; a Spanish residential IP passes. Country routes fail closed (`ProxyUnavailable`), never fall back to the home IP.
- Gateway search needs the app's full filter body: a short body gets 400.
- No creation-date sort exists (bundle `SORT_FIELDS`); default = relevance, promoted rows first → a sweep cursor must cover every page.
- `hasTaxes`/`includesTaxes` false on a dealer ad = net price (+21 % VAT); private sales carry no VAT → `price_is_net` stays unset.
- Liveness: 302 to `/…/segunda-mano/` = the site's own "ad gone" (Imperva never redirects); 404/410 = gone.
- Never press Enter in the contact box (resets the form, nothing sent); a "not sent" can still arrive — check relay mail before a re-send.
- Free VPN / datacenter exits get the bot page on load.

## Gaps
- Registration month: gateway `plateRegistrationDate` on some private ads; the page route has only the year (month parsed from "Matriculación: MM/YYYY" in the description when present).
- km-0 ads (`-devn`/`-kovn` URLs) sometimes answer 200 without the ad id → liveness `unknown`.
- Gateway `/details` statuses other than `active` and its answer for a removed ad are unknown (404/410 assumed).
- Gateway liveness (cheaper than the 2/h page budget) is unverified → `is_live` uses the page.
