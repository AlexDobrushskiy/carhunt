# marktplaats_nl — marktplaats.nl · 2dehands.be · 2ememain.be

| | |
|---|---|
| wall | CloudFront WAF: `/` is 403 to scripts, data URLs pass |
| route | plain HTTP; search = JSON API `/lrp/api/search`, ad = `window.__CONFIG__.listing` |
| pace | ≥6 s between loads, ≤60/run, reads after 12:00 (or via a proxy) |
| phone | private: hidden logged-out (no reveal); dealers: `seller.phoneNumber` on the ad page |
| messaging | site chat (`asq`) needs a login with SMS 2FA per new device → not set up |

## Query
`<origin>/lrp/api/search?l1CategoryId=91&limit=30&offset=N&query=<text>&attributesById[]=<id>&attributeRanges[]=<key>:<min|null>:<max|null>&sortBy=SORT_INDEX&sortOrder=DECREASING`
— codes in `codes.yaml` (domains, seller 10898/10899, fuel bev 11756, range keys, sort, query text per model).
`country` NL → marktplaats.nl, BE → 2dehands.be, BE + `extra={"lang": "fr"}` → 2ememain.be. Stops at a short page
or `maxAllowedPageNumber`.

## Rules (why)
- Never warm up on `/` (or any home page): CloudFront 403s it to scripts while the API passes.
- Messaging-site read budget: ≤60 loads/run and only after 12:00 on the home IP — read bursts get the home IP
  403'd on other messaging sites.
- Search rows carry no seller type: `seller_type` is set only when the query filtered on it.
- `constructionYear` is the year only → `first_registration = "YYYY"`; discover must not invent a month.
- 2dehands and 2ememain show the same ads (same `m…` id): dedupe on `site_ref`.
- Accounts: never rent a throwaway number for the SMS 2FA — it is asked at every new-device login and locks the
  account later. The 2dehands/2ememain account is separate from marktplaats.
- 404/410 = gone (skip, continue); 403/429 = blocked (stop the site).

## Gaps
- No reader for search-row sponsored flags or thumbnails; `created` comes only from the ad page
  (`stats.since`), search rows have a relative date label.
- No phone reveal and no sender (needs the SMS-2FA login).
- Fuel filter codes exist only for BEV; other fuels are left unfiltered.
