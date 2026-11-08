# carsbat_com — carsbat.com (VIN auction-history archive)

| | |
|---|---|
| kind | vin-history (vet): was this car sold at an EU dealer auction (OpenLane, BCA-type), at what price/km/damage |
| wall | Cloudflare |
| route | plain-chrome or the identity browser (lane + plain HTTP: "Just a moment") |
| account | free, e-mail confirmed; needed for the VIN search |
| phone / messaging | none |
| readers | URL/VIN helpers only — `lookup`/`ad`/`search`/`is_live` raise `Unsupported` |

## Lookup
- VIN search (login): `/en/vin-search/?query=<VIN>` → redirects to the lot when the VIN is archived (`vin_search_url`).
- Lot page (public): `/en/detail/<vin lowercase>-<hash>/` (`lot_vin(url)` gives the VIN back).
- Logged in, a lot shows price history (with/without VAT), sale date, country, km, damage flag, keys, seller type
  and ~30 photos.

## Rules (why)
- Cloudflare stops the lane and plain HTTP ("Just a moment", 11-01) → a non-automated browser.
- Photos load only through the browser session's own request (`page.request`); plain HTTP gets 403.
- Login (form `#id_login` / `#id_password` at `/accounts/login/`) belongs to the browsers/accounts modules
  (credentials from the secrets backend), never typed from a plugin.

## Gaps
- No lot-page parser: the page was never captured. Capture one logged-in lot page and write `lookup` + a synthetic
  fixture from it. A model browse page (`/en/<make>/<model>/`) exists; its shape is unknown.
