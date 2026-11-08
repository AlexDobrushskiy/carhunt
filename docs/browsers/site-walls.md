# Site walls (seed, measured Oct–Nov 2026)

> **Seed input for the sites module.** Each row becomes that site's `carhunt/sites/<site>/site.yaml` (keys: `name, wall, route, country_ip, pace{min_gap_s, max_loads_per_run, per_hour}, caps{phone_per_day, send_per_day, login_per_day, load_per_day}, account{needed_for[], verification, mail_from}, messaging, measured, notes`). Once the site.yaml files exist, the agent-facing table is **generated** (`carhunt browser site-table --write skills/carhunt-browsers/references/site-table.md`) and this file is history.
>
> Measured by one buyer on a residential home IP in Portugal, Agent Chrome, Oct 18 – Nov 6 2026. Limits are moving targets (mobile.de tightened three times in two weeks); re-measure anything older than ~3 months. "Home IP" = the buyer's residential IP; "Playwright" = lane, identity MCP or any Playwright-launched Chrome.

## Evidence

| site | wall | blocks | passes (read) | phone | message | account / verification | measured |
|---|---|---|---|---|---|---|---|
| mobile.de | Akamai | curl 403; any Playwright-launched Chrome; `--headless`; ~25 fast / ~60 paced loads per profile; home IP 403 after ~41 sweep loads in one morning | plain-chrome only (RSC flight data in page), ≥10–12 s, fresh profile per ~20 loads | in page data, no login | logged in ("E-Mail schreiben" → checkout form), identity copies | email + password; reset via emailed code; no SMS | 2026-11-06 |
| lacentrale.fr | DataDome | Playwright → slider; solving it inside Playwright → hard block; `--headless`; ~10 blocked hits/h flag the IP | plain-chrome, home page first (`--warm`), jar cookie; local solver 2/2 in plain-chrome | — | — | none | 2026-10-26 |
| leboncoin.fr | DataDome | fast search bursts → IP + cookie ban for hours; a poisoned `datadome` jar cookie blocked every browser; identity MCP slider on login, slide → 403; home IP 403 after ~160 ad reads | plain HTTP + jar cookie, ≥10–12 s, stop at first 403/429/challenge; 404/410 = ad gone | logged in, FR IP only, ≤40 reveals/day | logged in, FR IP only (`/reply/<id>`, 2500 chars); from a foreign IP officially off / silently dropped | signup needs a **French mobile + SMS** (foreign SMS never arrived) → rented one-time FR number worked; the account must live on ONE FR IP; a datacenter VPN IP later got a messaging soft block → FR residential proxy | 2026-11-05 |
| coches.net | Imperva ABP (reese84) behind CloudFront | Playwright attached at all → every agent browser on the home IP flagged for hours; bursts flag plain HTTP (5th load at 10 s = bot page); contact + phone APIs refuse any non-ES IP for every client tried (Playwright, raw CDP, curl_cffi, Camoufox, patchright, a normal Chrome); free VPN Gate / datacenter VPN → bot page | plain HTTP (`__INITIAL_PROPS__`), **≤2 page loads per rolling hour shared by all agents** | app API `…/details/<id>/phone` via ES IP | Camoufox + ES residential proxy; newlines typed as text (Enter resets the form); one click; wait ≤180 s for the contact-mail 200 | email account (Gigya) + email link; profile edit needs ES mobile + ES postcode (don't fake); photo app-only | 2026-11-03 |
| milanuncios.com | Imperva ABP | curl → challenge; phone endpoint 403 "fuera de España" from non-ES IP; 4th reveal per session 403 | one plain-chrome tab + in-page fetch | logged in + ES IP: 3 per sticky session, ≤9/day | logged in + ES IP, Camoufox **with media on** (modal in `#modal-react-portal`) | email + password, email link; no phone verification | 2026-11-03 |
| wallapop.com | none (API on CloudFront) | — | plain HTTP JSON API, 5 s | private sellers: none (chat only) | logged in, `es.wallapop.com/app/chat?itemId=<id>`, **≤300 chars** (silently truncated) | email + password; new-device login = email code | 2026-11-04 |
| kleinanzeigen.de | Akamai (reads not challenged) | account activation link: "IP-Bereich vorübergehend gesperrt" on a residential range; datacenter IPs 403 | plain HTTP, 6 s | private sellers: no reveal (only numbers typed in the ad text) | logged in (identity), inbox `m-nachrichten.html` | signup ok; activation link + SMS done by the owner on phone mobile data; later agent logins from home IP fine | 2026-11-02 |
| marktplaats.nl, 2dehands.be / 2ememain.be | CloudFront WAF (`/` 403 to scripts) | warming up on `/`; logins | plain HTTP JSON API (`--site nl\|be\|fr`), 6 s | hidden when logged out | needs login | **SMS 2FA at every new-device login** → never rent a number (locks the account); 2dehands account separate from marktplaats | 2026-11-01 |
| subito.it | Akamai + DataDome (dormant) | — | plain HTTP, 6 s | `/hades/v1/contacts/ads/<urn>`, no login | logged in (identity via plain-chrome `--profile`); off-screen window → `el.evaluate(e=>e.click())`; thread survives ad removal | SMS-verified phone for any login; accepted the owner's own foreign EU mobile | 2026-11-02 |
| standvirtual.com | CloudFront, no challenge (reCAPTCHA v3 on VIN reveal) | — | plain HTTP | decoded offline (AES-GCM, key from seller/stand id, site's own JS); VIN decoded the same way keyed by advert id | logged in (OLX Group login, master) | OLX Group account | 2026-11-04 |
| olx.pt | CloudFront WAF | any plain HTTP 403 (TLS/HTTP2 fingerprint) | site JSON API from inside one plain-chrome tab | logged out → 400 "Disallowed"; logged in with Bearer from `access_token` cookie → 200; 401 = stale pool token → `pw-identity seed --all` | logged in | OLX Group account | 2026-11-04 |
| custojusto.pt | client-fingerprint 403 | plain HTTP after ~50 ads at 6 s; phone POST 403 even from the page | real browser, ≥12–13 s, stop at first 403 | ✗ (use the form) | "Enviar mensagem" one-way form; a reply opens an inbox thread | login on the master only (pool copies lacked the session) | 2026-11-04 |
| autoscout24 (.de .at .it .es .fr .nl .be .com) | none triggered | — | plain HTTP `__NEXT_DATA__`, 6 s; `.be` needs `/nl/` or `/fr/` | in page data | guest "E-Mail senden" form (no login); .de/.nl form broken 2026-11-05 → email the dealer's own address | Google-only account → agents never type the owner's Google password; use guest forms | 2026-11-05 |
| carsbat.com (VIN auction archive) | Cloudflare | lane + curl "Just a moment" | plain-chrome / identity tab; images via `page.request` | — | — | free account (VIN search needs login) | 2026-11 |
| toyota.pt (recall / warranty) | reCAPTCHA grid | — | lane + local captcha solver, then in-page fetches; warranty sim needs the page's Bearer + `makeFullValidations=true` | — | — | none | 2026-10-27 |
| leparking.fr (FR aggregator) | Cloudflare | — | lane ✓; filters only via JS | — | — | none | 2026-11-02 |
| autouncle, gaspedaal.nl, willhaben.at, otomoto.pl, autohero.com, carvago.com | various (DataDome / Cloudflare) | — | lane ✓, plain-chrome ✓ | — | — | none | 2026-10-25 |

## Suggested site.yaml values

| site | route | country_ip | pace | caps | account.verification | messaging |
|---|---|---|---|---|---|---|
| mobile.de | plain-chrome | — | min_gap_s 12, max_loads_per_run 60; reads after midday; fresh profile per 20 | — | email-code | identity, logged in |
| lacentrale.fr | plain-chrome (`--warm` home) | — | min_gap_s 12 | — | none | — |
| leboncoin.fr | http (+ jar cookie) → geo FR for account steps | FR (login, phone, message) | min_gap_s 12; geo route ≤8 loads/55 min, ≥60 s gap | phone_per_day 40 | sms-once (FR mobile only) | geo FR browser, logged in, 2500 chars |
| coches.net | http | ES (phone, message) | per_hour 2 (all agents) | — | email-link | camoufox + ES proxy |
| milanuncios.com | plain-chrome | ES (phone, message) | min_gap_s 12 | phone_per_day 9 (+ ≤3 per sticky session) | email-link | camoufox + ES proxy, media on |
| wallapop.com | http | — | min_gap_s 5 | — | email-code | identity, ≤300 chars/message |
| kleinanzeigen.de | http | — | min_gap_s 6 | — | email-link + SMS (owner's own number; activation on mobile data) | identity, logged in |
| marktplaats.nl | http | — | min_gap_s 6 | — | sms-every-login | ✗ |
| subito.it | http | — | min_gap_s 6 | — | SMS (owner's own number accepted) | identity via plain-chrome `--profile` |
| standvirtual.com | http | — | min_gap_s 6 | — | email (OLX Group) | identity (master) |
| olx.pt | plain-chrome (in-page API) | — | min_gap_s 6 | — | email (OLX Group) | identity |
| custojusto.pt | plain-chrome | — | min_gap_s 12 | — | email | one-way form |
| autoscout24 | http | — | min_gap_s 6 | — | none (guest form; account is Google-only) | guest form / dealer email |
| carsbat.com | plain-chrome / identity | — | — | — | email | — |
| toyota.pt | lane + captcha | — | — | — | none | — |
| leparking.fr | lane | — | — | — | none | — |

Missing `pace`/`caps` in a site.yaml → `carhunt pace` applies its conservative default. `account.verification` drives `carhunt sms policy`: only `sms-once` allows a rented number, `sms-every-login` refuses, anything else refuses (fail closed) — so write free text like "SMS (owner's own number)" only where rental must stay off. Site name lookup (`pace`, site-table): `name`, `domain`/`domains`, else the plugin dir.
