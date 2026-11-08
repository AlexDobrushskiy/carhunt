# sites — marketplace plugins + liveness

One plugin per marketplace under `carhunt/sites/<pkg>/` (`pkg` = site id with `.`/`-` → `_`). Reads only: logins, phone reveals behind a login, and senders live in browsers/contact.

## Site matrix
Rendered from every `site.yaml` (`python -m carhunt.sites.matrix --write docs/sites.md`; a test fails when it drifts).

<!-- site-matrix:begin -->
| site | countries | wall | read route | country IP | account needed for | phone | cursor | messaging | measured |
|---|---|---|---|---|---|---|---|---|---|
| autoscout24 | DE, AT, IT, ES, FR, NL, BE, LU | none (CloudFront, no challenge seen) | http | — | none | page | first_seen | guest 'E-Mail senden' form (no login); .de/.nl form unreliable 11-05 → dealer's own email | 2026-11-06 |
| carsbat.com | DE | Cloudflare | plain-chrome | — | vin | none | full | none: auction archive, no sellers to contact | 2026-11-01 |
| coches.net | ES | Imperva ABP (reese84) via CloudFront | http | — | message | reveal | full | logged in, Spanish residential IP, non-Playwright browser: 'Contactar' once → contact-mail 2xx; never Enter in the box (resets the form) | 2026-11-07 |
| custojusto.pt | PT | client-fingerprint 403 (plain HTTP clients blocked; the same IP passes in a real browser) | lane | — | message | none | newest_id | 'Enviar mensagem' = contact form (one-way); the seller's reply opens a thread in the CJ inbox (11-05) | 2026-11-07 |
| kleinanzeigen.de | DE | Akamai Bot Manager (reads not challenged) | http | — | message | text-only | newest_id | site chat, logged in (inbox /m-nachrichten.html); sender lives in contact | 2026-11-01 |
| lacentrale.fr | FR | DataDome | plain-chrome | — | none | none | full | site's message-seller form on the ad page (not measured here; sender lives in contact) | 2026-10-30 |
| leboncoin.fr | FR | DataDome | http | — | phone, message | reveal-login | newest_id | logged in, French IP only: 'Envoyer un message' → /reply/<id> (2500 chars); from a foreign IP silently dropped | 2026-11-06 |
| leparking.fr | FR | Cloudflare | lane | — | none | none | full | none: an aggregator — contact the seller on the source site | 2026-11-02 |
| marktplaats.nl | NL, BE | CloudFront WAF (home page / is 403 to scripts; data URLs pass) | http | — | message, phone | none | newest_id | site chat ('asq' in seller.contactOptions) needs a logged-in account → unusable (SMS 2FA); dealers' own phone/website are on the ad page | 2026-11-07 |
| milanuncios.com | ES | Imperva ABP (reese84) | plain-chrome | — | phone, message | reveal-login | newest_id | logged in + Spanish IP, media on: 'Mensaje' → 'Escribir otro mensaje' → 'Enviar' once → chat/contact 200 (11-03) | 2026-11-07 |
| mobile.de | DE | Akamai | plain-chrome | — | message | page | newest_id | 'E-Mail schreiben' form (/checkout/core/<id>), logged in only; sender lives in contact | 2026-11-06 |
| olx.pt | PT | CloudFront WAF (403 to every plain HTTP client, even with full browser headers) | plain-chrome | — | phone, message | reveal-login | full | site chat, logged in; ads with contact.phone=false are chat-only | 2026-11-07 |
| standvirtual.com | PT | none (CloudFront, no challenge on reads; reCAPTCHA v3 only on the site's VIN reveal button) | http | — | message | decode | newest_id | site chat, logged in (OLX Group account); sender lives in contact | 2026-11-07 |
| subito.it | IT | Akamai + DataDome (not triggered by plain HTTP) | http | — | message | reveal | newest_id | site chat 'Contatta', logged in (inbox areariservata.subito.it/messaggi); a thread survives the ad's removal | 2026-11-01 |
| wallapop.com | ES | none (public JSON API on CloudFront) | http | — | message | page | newest_id | logged-in site chat es.wallapop.com/app/chat?itemId=<hash id>; ≤300 chars per message (longer text is cut silently) | 2026-11-06 |
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
- Tests: `carhunt.sites.testing.FakeNet` (canned answers, no network); `CARHUNT_FAKE_SITES=1` registers the test-only `fake` site (`CARHUNT_FAKE_SITES_FIXTURES=<ads.json>`, `CARHUNT_FAKE_SITES_BLOCK=search,ad,live`, `CARHUNT_FAKE_PHOTO_BASE=<local image server>`; unset = no photos, since cardb downloads every photo URL).

## Cursors and price changes
- `site.yaml cursor.strategy` (read by discover, `carhunt/discover/cursor.py`): `newest_id` = newest first, numeric `site_ref` grows → stop at the stored max; `first_seen` = newest first with opaque ids (AS24 UUIDs) → stop at last run's first organic id / its created time; `full` = page the whole filtered set every run (coches.net relevance order, olx.pt ignores sort, unmeasured sites).
- Newest-first sweeps never revisit known ads, so **price changes on known listings are caught by liveness**: a live page also yields the current price (parsed from the same page, no extra load); a change is written as a minimal upsert `{url, price}` → cardb price history + `price_change` event. Net (ex-VAT) page prices are skipped (cardb stores gross).
- Price from the liveness page: autoscout24, standvirtual.com, kleinanzeigen.de, subito.it, marktplaats.nl, custojusto.pt, milanuncios.com, mobile.de, coches.net (page route), leboncoin.fr. Not available (ad data comes from a separate API): olx.pt, wallapop.com — their liveness reports state only.

## Rules (why)
- Page's own data first (`__NEXT_DATA__`, RSC flight, `__INITIAL_PROPS__`, site JSON API): 1 request instead of ~50 browser requests → fewer loads, fewer bans.
- Every request takes a slot in the shared ledger first (`access.pace.acquire(site, kind, via=<exit CC>)`; kinds `load` page, `api` JSON read, `phone` reveal; limits from site.yaml `pace`/`caps`, see docs/browsers.md) — unpaced parallel agents on one IP get sites banned. A proxied request is paced on its exit (own rate budget, same day caps). The transport waits ≤180 s for a gap slot, else `PaceExceeded` (stop the site).
- Stop a site at the first block (401/403/429/5xx/bot page → `Blocked`); 404/410/site marker = that ad is gone → `Gone`, keep going — stopping on a gone ad leaves the rest of the run undone.
- Missing page data = `Blocked`, never `Gone`: a changed page or a wall says nothing about the ad.
- Phone reveal slots are taken before the call (a 403 still counts); day caps in site.yaml `caps`.
- Country-IP steps go through `access.proxy`, fail-closed: no verified exit → no request (ES-only APIs 403 every non-ES client).
- Liveness removes on 404/410/marker at once, on a soft signal (redirect to a list page) only at the 2nd signal ≥1 h later, never on block/timeout; relists only what it removed — a one-off string check can mark live cars removed.
- `pace.read_after` (messaging sites) is enforced by discover's scheduler, not the transport: liveness at 04:30 and sends at midday don't collide, but sweep reads would.
- `pace.fresh_profile_every`: the transport closes the tab and opens a throwaway profile every N browser loads (mobile.de: Akamai burst limit per profile ~25 fast/~60 paced loads).
- Liveness writes only via cardb (`PATCH /listings/{id}` + `ad_check` event); it never touches car status.

## Config
`sites.enabled` (ids from `carhunt site list`; doctor fails on unknown ids) and `sites.overrides.<site>` (tighten site.yaml numbers): [`config.example.yaml`](../config.example.yaml) `sites:`.
State + logs (never in the repo): `$CARHUNT_HOME/sites/liveness.db`, `$CARHUNT_HOME/sites/liveness/{checks-<date>.jsonl,runs.jsonl,launchd.log}`.

## Add a site
1. `carhunt/sites/<pkg>/site.yaml` — validate against `site.schema.json`; every pace/cap number carries its `why` and `measured` date.
2. `codes.yaml` — make/model slugs/ids + filter codes (the query builder reads only this).
3. `plugin.py` — `class Plugin(BaseSite)`, `pkg = "<pkg>"`; copy `autoscout24/plugin.py`. Transport only via `self.net.get/json` (HTTP) or `self.net.browser_get(url, mode=fetch|goto)` (browser routes); parse functions pure (text in, model out).
4. `README.md` — wall, route, pace, phone, messaging, rules with why, gaps. No account names, phones, ad ids.
5. `carhunt/sites/tests/test_<pkg>.py` + `tests/fixtures/<pkg>/` — hand-made pages in the site's real shape: query builder, search + ad parsers, Blocked/Gone, liveness rules.
6. Measure with ≤3 read-only public loads (`carhunt site <id> search --max 5`), then `python -m carhunt.sites.matrix --write docs/sites.md` and `carhunt browser site-table --write skills/carhunt-browsers/references/site-table.md` (both have drift tests).

## Gaps
- olx.pt / wallapop.com liveness gives no price (API-only ad data); liked cars there need a periodic `carhunt site <id> ad` re-read for prices.
- lacentrale.fr, leparking.fr, carsbat.com: URL builders only — search/ad/live raise `Unsupported`.
- Browser-route sites (mobile.de, olx.pt, custojusto.pt, milanuncios.com, lacentrale.fr, leparking.fr, carsbat.com) open one `access.session.tab(route, site=, country=, fresh=)` per run; the tab blocks on walls but the transport paces (`goto(..., paced=False)`). Needs Chrome + playwright (doctor checks).
