# Country IPs (proxies, geo browser) and rented SMS numbers

Reference for the `carhunt-browsers` skill. Config: `net.proxy.*`, `accounts.sms.*` (docs/browsers.md).

## When a country IP is needed
Some sites gate by **country**, not reputation: coches.net and milanuncios (same vendor stack) refuse the contact/phone APIs from non-ES IPs ("fuera de España"); five different clients failed identically from abroad before an ES residential IP passed (11-02/03). leboncoin messaging/reveals from a foreign IP are off or silently dropped. The site row's `country_ip` says which steps.
- Only those steps; reads stay on the home IP / http. Why: residential proxies are paid per GB.
- No proxy configured → the step is not possible; report it, don't improvise a free VPN.

## Proxy rules
| rule | why |
|---|---|
| Residential (or mobile) provider; free/public VPNs and datacenter ranges are useless on serious walls | VPN Gate residential IPs → Imperva bot page on the first load (public list = flagged); a datacenter VPN IP got a messaging soft block (leboncoin, 11-05) |
| **Fail closed**: exit country verified before the first site load; mismatch/unknown → `ProxyUnavailable`, no request leaves | a dead OpenVPN left a SOCKS forwarder serving the home IP (11-02) |
| One sticky session per run (≤30 min) | rotating a new IP per load → DataDome slider on the 3rd load (11-06) |
| Media/images off where the site allows; Firefox Widevine/OpenH264 downloads off | 17 MB of a 66 MB campaign was Widevine (11-03); milanuncios needs media on (click does nothing without it) |
| Behind a slow proxy, extend app XHR timeouts; wait ≤180 s for the send answer | 10 s app timeout aborted the real POST (11-03) |
| Credentials only inside the adapter (`carhunt proxy` never prints a URL with credentials); Chrome gets a local no-auth forwarder that dies with the tunnel | Chrome can't take proxy auth on the command line; a leaked URL = a leaked secret |

- Test: `carhunt proxy test ES` → exit IP country + ASN type, nothing else. Do it once after setup and after any provider change.
- Python: `access.proxy.get(country, sticky_minutes)`; `session.tab(route, country="ES")` does get + verify.
- Cost reference: a whole coches/milanuncios send campaign used 66 MB of a ~$5 / 1 GB plan (11-03).

## Geo browser (one account, one IP)
- An account created on a country IP **lives on that one IP forever**; the home IP never logs into it; its profile (`profiles/geo-<cc>`) never joins the identity pool's cookie sync. Why: provider forum reports of bans on IP hopping; owner rule (11-02).
- It's a single shared resource → **lease** it (Python `with access.geo.lease(CC) as g:` or `session.tab("plain-chrome", country=CC)`; `carhunt browser geo status` shows the holder). Why: a second caller once killed the holder's step (11-04).
- Pace on residential: ≤8 loads per 55 min, ≥60 s gap (leboncoin FR route).

## Camoufox (optional, `camoufox` route)
- `os="macos"` always (a random Windows identity turns on canvas noise) and an explicit locale (geoip produced `es-PT`).
- Reach React state with `main_world_eval`; read API status from the driver's network events, not a page hook (Camoufox saw the real 403; Chrome only `net::ERR_FAILED`).

## Rented SMS numbers
| rule | why |
|---|---|
| Rent **only for verify-once sites** (SMS at signup, never again); never for sites with SMS 2FA at every new-device login (marktplaats / 2dehands) | the number dies after one SMS → the next challenge locks the account |
| Prefer the owner's own long-lived mobile when the site accepts foreign numbers | subito accepted a foreign EU mobile (11-02); a rented number can't be swapped later (change needs a code to the dead number; support wants a bill + ID) |
| Each rental is a purchase → owner's OK first (site, country, price) | spend rule |
| Pick the provider/pool by **per-service success rate**, not price; pay only on received code; cancel = refund | 5sim FR leboncoin 0.4–3.7 % vs SMSPool ~30 %; the cheap pool returned a recycled number ("already linked to an account"); premium pool worked in 25 s (11-02) |
| The rental IP matters: sign up from the target country's IP, then that IP is the account's IP forever | foreign-IP signup got stuck at the phone step (leboncoin, 11-02) |
| Record that the account has **no SMS recovery** in the site row notes | any future SMS challenge = lockout |

Commands: `carhunt sms policy <site>` (exit 0 allowed / 3 refused; reads site.yaml `account.verification`: `sms-once` allows; `sms-own`, `sms-every-login`, anything else/unknown refuse = fail closed) · `carhunt sms rent --site <domain> --country <CC> --service <provider id> [--pool P] [--dry-run]`. Python: `sms.rent(country, service, site=)` → `sms.wait_code(rental)` (no code in time → cancelled, refunded).

Which sites accepted what (Nov 2026): leboncoin — French mobile only, rented FR number OK (verify-once); subito — any SMS-capable phone incl. foreign EU; kleinanzeigen — owner's own number + activation on mobile data; marktplaats / 2dehands — SMS at every login → no rental; coches.net — profile edit wants an ES mobile (not done).
