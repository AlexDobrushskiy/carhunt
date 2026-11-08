# autoscout24 — AutoScout24 (.de .at .it .es .fr .nl .be .lu)

| | |
|---|---|
| wall | none triggered (CloudFront) |
| route | plain HTTP; all data in Next.js `__NEXT_DATA__` (list + ad) |
| pace | ≥6 s between loads, ≤120/run |
| phone | in page data (`seller.phones[].callTo`), privates too — no reveal |
| messaging | guest "E-Mail senden" form; sender lives in contact |

## Query
`/lst/<make>/<model>?atype=C&cy=<country>&fregfrom&kmto&pricefrom/priceto&fuel&custtype=P|D&sort=age&desc=1&page=N` — codes in `codes.yaml` (domains, fuel, seller, sort, make/model slugs). 20 rows/page.

## Rules (why)
- Belgium needs `/nl/` or `/fr/` before `/lst`: bare `/lst` is 404 on .be.
- Never set a sweep cursor from a sponsored row (`searchResultType != Organic`): they ignore filters (11-03).
- `isNetPrice` = dealer price without VAT: discover stores gross + `price_basis=net` (net asks passed the price filter, 11-03).
- 308 = the ad's slug changed, same uuid: liveness follows once; 410 = gone.
- .de/.nl guest form sent nothing on 11-05 (0/5 replies) → contact uses the dealer's own email there.
- Account login is Google-only: agents never type the owner's Google password; the guest form needs no login.
