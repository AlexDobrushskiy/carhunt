# sites — marketplace plugins + liveness

One plugin per marketplace under `carhunt/sites/<pkg>/` (`pkg` = site id with `.`/`-` → `_`). Reads only: logins, phone reveals behind a login, and senders live in browsers/contact.

## Site matrix
Rendered from every `site.yaml` (`python -m carhunt.sites.matrix --write docs/sites.md`; a test fails when it drifts).

<!-- site-matrix:begin -->
| site | countries | wall | read route | country IP | account needed for | phone | messaging | measured |
|---|---|---|---|---|---|---|---|---|
| autoscout24 | DE, AT, IT, ES, FR, NL, BE, LU | none (CloudFront, no challenge seen) | http | — | none | page | guest 'E-Mail senden' form (no login); .de/.nl form unreliable 11-05 → dealer's own email | 2026-11-06 |
| leboncoin.fr | FR | DataDome | http | — | phone, message | reveal-login | logged in, French IP only: 'Envoyer un message' → /reply/<id> (2500 chars); from a foreign IP silently dropped | 2026-11-06 |
| marktplaats.nl | NL, BE | CloudFront WAF (home page / is 403 to scripts; data URLs pass) | http | — | message, phone | none | site chat ('asq' in seller.contactOptions) needs a logged-in account → unusable (SMS 2FA); dealers' own phone/website are on the ad page | 2026-11-07 |
<!-- site-matrix:end -->

Per-site walls, pace numbers with their why, quirks: `carhunt/sites/<pkg>/README.md` + `site.yaml`.

## Commands
| command | what |
|---|---|
| `carhunt site list` | ids, wall, route, phone source, measured date |
| `carhunt site <id> search --make M --model X [--country CC --price-max N --year-min Y --km-max K --fuel bev --seller private\|dealer --sort newest --pages N --max N --extra k=v]` | cards (JSON lines) |
| `carhunt site <id> ad URL…` (`--raw` keeps the site JSON) | full parsed ads |
| `carhunt site <id> phone URL… [--reveal]` | phones from page data / offline decode; `--reveal` allows the site's phone endpoint (pace kind `phone`, day caps) |
| `carhunt site <id> live URL…` | `{state: live\|removed\|unknown, evidence, soft}` |
| `carhunt site <id> info` | the site.yaml |
| `carhunt liveness [--site S] [--car ID] [--daily] [--sample N] [--limit N] [--max-prio N] [--until HH:MM] [--proxy-priority] [--dry-run] [--json]` | check cardb listings, write gone/back through cardb |
| `carhunt liveness --plist [--at 04:30]` | launchd job for orchestrate's `schedule install` |

`site` exit codes: 0 ok · 2 blocked or pace exceeded (stop this site) · 3 every URL gone · 4 unsupported. `--dry-run` = reads only (refuses `--reveal`). `liveness --car` exit: 0 an ad is live · 4 all gone · 5 couldn't tell.

## Python interface (discover, contact, vet)
- `carhunt.sites.base`: `get(id)`, `ids()`, `metas()`, `for_url(url)`; `Gone`, `Unsupported`; `Blocked`/`PaceExceeded` re-exported from `carhunt.access.errors`.
- `Site`: `search(SearchQuery) -> Iterator[Card]`, `ad(url) -> RawAd`, `phone(ad, reveal=False) -> list[str]`, `is_live(url) -> Liveness`, `owns(url)`, `ad_id(url)`, `close()`.
- `carhunt.sites.model`: `SearchQuery` (one make/model per query), `Card`, `RawAd` (+`Seller`), `Liveness`. Plugins parse; discover normalises (VAT, scope, options).
- Tests: `carhunt.sites.testing.FakeNet` (canned answers, no network); `CARHUNT_FAKE_SITES=1` registers the synthetic `fake` site (`CARHUNT_FAKE_SITES_FIXTURES=<ads.json>`, `CARHUNT_FAKE_SITES_BLOCK=search,ad,live`).

## Rules (why)
- Page's own data first (`__NEXT_DATA__`, RSC flight, `__INITIAL_PROPS__`, site JSON API): 1 request instead of ~50 browser requests → fewer loads, fewer bans.
- Every load passes the pace gate (`access.pace`, shared by all agents on the IP; site.yaml `pace`) — parallel agents on one IP got sites banned (coches.net 11-03, leboncoin 10-30).
- Stop a site at the first block (401/403/429/5xx/bot page → `Blocked`); 404/410/site marker = that ad is gone → `Gone`, keep going — two runs stopped leboncoin on a 410 and left ~200 ads undone (11-04/05).
- Missing page data = `Blocked`, never `Gone`: a changed page or a wall says nothing about the ad.
- Phone reveal slots are taken before the call (a 403 still counts); day caps in site.yaml `caps`.
- Country-IP steps go through `access.proxy`, fail-closed: no verified exit → no request (ES-only APIs 403 every non-ES client, 11-02/03).
- Liveness removes on 404/410/marker at once, on a soft signal (redirect to a list page) only at the 2nd signal ≥1 h later, never on block/timeout; relists only what it removed — an ad-hoc string check once marked 2 live cars removed (11-04).
- Liveness writes only via cardb (`PATCH /listings/{id}` + `ad_check` event); it never touches car status.

## Config
```yaml
sites:
  enabled: [autoscout24, standvirtual.com, …]   # ids from `carhunt site list`; doctor fails on unknown ids
```
State + logs (never in the repo): `$CARHUNT_HOME/sites/liveness.db`, `$CARHUNT_HOME/sites/liveness/{checks-<date>.jsonl,runs.jsonl,launchd.log}`.

## Add a site
1. `carhunt/sites/<pkg>/site.yaml` — validate against `site.schema.json`; every pace/cap number carries its `why` and `measured` date.
2. `codes.yaml` — make/model slugs/ids + filter codes (the query builder reads only this).
3. `plugin.py` — `class Plugin(BaseSite)`, `pkg = "<pkg>"`; copy `autoscout24/plugin.py`. Transport only via `self.net.get/json` (HTTP) or `self.net.browser_get(url, mode=fetch|goto)` (browser routes); parse functions pure (text in, model out).
4. `README.md` — wall, route, pace, phone, messaging, rules with why, gaps. No account names, phones, ad ids.
5. `carhunt/sites/tests/test_<pkg>.py` + `tests/fixtures/<pkg>/` — **hand-made synthetic** pages in the site's real shape (VIN `SYN…`, phones `+cc 555…`, `example.invalid` hosts): query builder, search + ad parsers, Blocked/Gone, liveness rules.
6. Measure with ≤3 read-only public loads (`carhunt site <id> search --max 5`), then `python -m carhunt.sites.matrix --write docs/sites.md`.

## Gaps
- Browser-route sites (mobile.de, olx.pt, custojusto.pt, milanuncios.com, lacentrale.fr, leparking.fr, carsbat.com) need `carhunt.access.session.tab`; without the browsers module they raise on first read (doctor warns).
- Without `carhunt.access.pace` pacing is in-process only (one agent); the shared ledger comes with the browsers module.
