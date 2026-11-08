# leboncoin_fr — leboncoin.fr

| | |
|---|---|
| wall | DataDome |
| route | plain HTTP + a `datadome` cookie from a real browser's trust jar; data in Next.js `__NEXT_DATA__` (list + ad) |
| pace | ≥12 s between loads, ≤150 loads/run, reads after 12:00 (messaging window first) |
| phone | "Voir le numéro" only logged in, French IP, ≤40/day → `phone(reveal=True)` is `Unsupported` here |
| messaging | logged in, French IP only: `/reply/<id>` form (2500 chars); sender lives in contact |

## Query
`/recherche?category=2&u_car_model=<CODE>&fuel=4&regdate=<lo>-<hi>&mileage=min-<km>&price=<lo>-<hi>&owner_type=private|pro&sort=time&order=desc&page=N`
— codes in `codes.yaml` (`u_car_model`, `u_car_brand`, fuel, seller, sort). Open range end = `min`/`max`. A model missing
from the table falls back to `text=<make> <model>` (filter the titles afterwards). 35 rows/page, ≤100 pages.
`regdate` is the model year; first registration is the ad's `issuance_date` (MM/YYYY).

## Cookie (transport)
The plugin sends `Cookie: datadome=<v>` and keeps the rotated value from each `Set-Cookie` for the run. Source:
`Plugin(cookie=...)` (value or callable), default `carhunt.access.jar.get("leboncoin.fr", "datadome")`. No
cookie → `Blocked("datadome-no-cookie")` before any request: one real-browser home-page load (no login) fills the jar.

## Rules (why)
- ≥10–12 s pace, stop at the first 403/429/challenge, don't retry the same hour: fast search bursts hard-ban the IP
  and the cookie for hours.
- ≤150 ad reads per run: DataDome 403s at ~160+ reads per IP.
- 404/410 (title "Annonce introuvable") or a non-`active` status = the ad is gone → `Gone`, skip it, keep going
  (stopping on a 410 leaves the rest of the run undone).
- A block can live in the **cookie**, not the IP: a banned `datadome` cookie in the shared jar blocks every browser
  until its row is deleted. On a 403: test a fresh browser; if it passes, delete the jar's leboncoin row.
- "Access (is) temporarily restricted" = hard block → stop for hours (`datadome-hard-block`).
- A slider on the refresh page: solve it once in that same non-automated browser; solving it in an automated
  (Playwright) browser → hard block.
- Reads after the messaging window, or from another exit IP: sweep reads get the messaging IP 403'd.
- Logged-in actions (phone, message) live on ONE French IP: the account was created with a rented SMS number, so a
  new SMS challenge = lockout. ≤40 reveals/day, take the slot before the click (a 403 still counts).
- Residential exit: one sticky session per run, ≤8 loads/55 min, ≥60 s apart — a new IP per load gets a slider within
  a few loads. Datacenter VPN IPs get a messaging soft block.
- Never "Faire une offre": a price offer is the owner's decision.

## Gaps
- `u_car_brand`/`owner_type=pro` values mirror the ads' own attribute values; the filters themselves are unverified.
  Sort by price: unverified (site default order).
- Promoted rows (`options.booster`/`sub_toplist`) are not flagged as `sponsored`: their effect on order is unknown.
  Use the numeric `list_id` (monotonic) as the cursor, not the first row.
- Only the electric `fuel=4` code is known.
