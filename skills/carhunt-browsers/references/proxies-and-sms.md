# Country IPs (proxies, geo browser) and rented SMS numbers

Reference for the `carhunt-browsers` skill. Config: `net.proxy.*`, `accounts.sms.*` (docs/browsers.md).

## When a country IP is needed
Some sites gate by **country**, not reputation: coches.net and milanuncios (same vendor stack) refuse the contact/phone APIs from non-ES IPs ("fuera de España") for every client. leboncoin messaging/reveals from a foreign IP are off or silently dropped. The site row's `country_ip` says which steps.
- Only those steps; reads stay on the home IP / http. Why: residential proxies are paid per GB.
- No proxy configured → the step is not possible; report it, don't improvise a free VPN.

## Proxy rules
| rule | why |
|---|---|
| Residential (or mobile) provider; free/public VPNs and datacenter ranges are useless on serious walls | public VPN IPs (e.g. VPN Gate) are on block lists → Imperva bot page on the first load; datacenter IPs get messaging soft blocks (leboncoin) |
| **Fail closed**: exit country verified before the first site load; mismatch/unknown → `ProxyUnavailable`, no request leaves | a dead tunnel can leave a forwarder serving the home IP |
| One sticky session per run (≤30 min) | a new IP per load → DataDome slider within a few loads |
| Media/images off where the site allows; Firefox Widevine/OpenH264 downloads off | Widevine alone can be a quarter of a campaign's traffic; milanuncios needs media on (click does nothing without it) |
| Behind a slow proxy, extend app XHR timeouts; wait ≤180 s for the send answer | a 10 s app timeout aborts the real POST |
| Credentials only inside the adapter (`carhunt proxy` never prints a URL with credentials); Chrome gets a local no-auth forwarder that dies with the tunnel | Chrome can't take proxy auth on the command line; a leaked URL = a leaked secret |

- Test: `carhunt proxy test ES` → exit IP country + ASN type, nothing else. Do it once after setup and after any provider change.
- Python: `access.proxy.get(country, sticky_minutes)`; `session.tab(route, country="ES")` does get + verify.
- Cost reference: a whole coches/milanuncios send campaign ≈ 66 MB (a ~$5 / 1 GB plan).

## Geo browser (one account, one IP)
- An account created on a country IP **lives on that one IP forever**; the home IP never logs into it; its profile (`profiles/geo-<cc>`) never joins the identity pool's cookie sync. Why: IP hopping gets accounts banned.
- It's a single shared resource → **lease** it (Python `with access.geo.lease(CC) as g:` or `session.tab("plain-chrome", country=CC)`; `carhunt browser geo status` shows the holder). Why: a second caller kills the holder's step.
- Pace on residential: ≤8 loads per 55 min, ≥60 s gap (leboncoin FR route).

## Camoufox (optional, `camoufox` route)
- `os="macos"` always (a random Windows identity turns on canvas noise) and an explicit locale (geoip produced `es-PT`).
- Reach React state with `main_world_eval`; read API status from the driver's network events, not a page hook (Camoufox saw the real 403; Chrome only `net::ERR_FAILED`).

## Rented SMS numbers
| rule | why |
|---|---|
| Rent **only for verify-once sites** (SMS at signup, never again); never for sites with SMS 2FA at every new-device login (marktplaats / 2dehands) | the number dies after one SMS → the next challenge locks the account |
| Prefer the owner's own long-lived mobile when the site accepts foreign numbers | subito accepts a foreign EU mobile; a rented number can't be swapped later (change needs a code to the dead number; support wants a bill + ID) |
| Each rental is a purchase → owner's OK first (site, country, price) | spend rule |
| Pick the provider/pool by **per-service success rate**, not price; pay only on received code; cancel = refund | 5sim FR leboncoin 0.4–3.7 % vs SMSPool ~30 %; cheap pools return recycled numbers ("already linked to an account") |
| The rental IP matters: sign up from the target country's IP, then that IP is the account's IP forever | foreign-IP signup gets stuck at the phone step (leboncoin) |
| Record that the account has **no SMS recovery** in the site row notes | any future SMS challenge = lockout |

Commands: `carhunt sms policy <site>` (exit 0 allowed / 3 refused; reads site.yaml `account.verification`: `sms-once` allows; `sms-own`, `sms-every-login`, anything else/unknown refuse = fail closed) · `carhunt sms rent --site <domain> --country <CC> --service <provider id> [--pool P] [--dry-run]`. Python: `sms.rent(country, service, site=)` → `sms.wait_code(rental)` (no code in time → cancelled, refunded).

Which sites accept what: leboncoin — French mobile only, rented FR number OK (verify-once); subito — any SMS-capable phone incl. foreign EU; kleinanzeigen — owner's own number + activation on mobile data; marktplaats / 2dehands — SMS at every login → no rental; coches.net — profile edit wants an ES mobile.
