---
name: carhunt-browsers
description: Use before any carhunt browser or site-access work — reading listings or ads on classifieds (mobile.de, AutoScout24, leboncoin, coches.net, Wallapop, kleinanzeigen, Subito, OLX…), revealing a seller phone, opening a site chat or contact form, logging in or creating a site account, email/SMS verification codes, renting an SMS number, a residential proxy or country IP ("fuera de España", geo-gated), pacing and day caps, or dispatching subagents that browse. Also on any wall: 403, "Access denied", captcha, slider, "Just a moment", DataDome, Akamai, Imperva, Cloudflare, blank page, bot page, "Browser is already in use", 401 on a logged-in API. Picks http vs lane vs identity vs plain-chrome vs camoufox; has the escalation ladder, per-site table, pacing, proxy/SMS/account policy and troubleshooting.
---

# carhunt browsers

Agents never touch the owner's own Chrome (no extension, no CDP attach, no profile copy). Every browser here is **Agent Chrome** (`agent-chrome`: a re-signed clone of the installed Chrome under its own bundle id) or Camoufox. Never launch from `/Applications/Google Chrome.app` (macOS takes the agent process for the owner's Chrome: Dock click activates a windowless agent, Quit fails) and never Chrome for Testing (sites treat it differently).

Names below are the defaults `carhunt browser mcp-config` prints (prefix `browsers.mcp_name_prefix`, default `ch-`): lanes `ch-lane` + `ch-lane-a…d`, identity master `ch-identity` + pool copies `ch-identity-a…d`. If your install uses others, map them 1:1.

## Which route

| route | what | use for |
|---|---|---|
| `http` | plain HTTP (curl_cffi if installed); `carhunt site <name> …` helpers | **reads first**: most classifieds ship full data (often phones) in `__NEXT_DATA__` / RSC / JSON APIs: 1 request instead of ~50 |
| lane `ch-lane`, `ch-lane-a…d` | Playwright MCP, throwaway in-memory context, headless presenting headed UA | JS pages without a login |
| identity `ch-identity`, `ch-identity-a…d` | Playwright MCP on persistent profiles holding the site logins; one holder per browser | logged-in steps only (messages, phone reveals, account pages) |
| `plain-chrome` | Agent Chrome launched like a person (debug port only, headed off-screen); attach after the first load | Akamai / DataDome sites that block Playwright-*launched* Chrome; `--profile` = on an identity profile |
| `camoufox` | anti-detect Firefox (optional install) | Imperva sites behind a country proxy (send/phone steps) |

Scripts: `from carhunt.access.session import tab` → `with tab("plain-chrome", site="mobile.de") as t: status = t.goto(url); t.content()` (paced + wall-checked; on browser routes `t` is also the Playwright page); `country="ES"` adds a fail-closed proxy (http, lane, camoufox; plain/identity refuse a country unless a geo lease). Per-site route: [references/site-table.md](references/site-table.md) (generated from `carhunt/sites/*/site.yaml`). **The site row wins over the ladder** (e.g. Imperva: never Playwright).

## Blocked? Escalation ladder — never settle for "blocked"
Move up after **ONE** blocked hit per rung. Why: every blocked hit raises the site's bot score; ~10 blocked hits in an hour can flag the home IP.
1. `http` (site helper / plain request)
2. lane (`ch-lane`; subagents their own `ch-lane-x`)
3. identity MCP (real history; some checks pass only here)
4. `plain-chrome fetch|open` (shared profile seeded from the trust-cookie jar; `--warm <home>` for DataDome sites that captcha a cold deep link)
5. `plain-chrome --profile <identity profile> open …` after `pw-identity acquire <you> --any` (plain launch + real history)
6. A captcha is showing → **solve it yourself in that same browser** (`carhunt captcha solve --cdp http://127.0.0.1:PORT --target TARGET`; MCP tabs: `--lane|--identity[-x] --url <part>`). Why same browser: the solve cookie is tied to that profile; the jar then carries it to the others. Max 2 attempts per run, 6 per site per 6 h (solver enforces).
7. Solver failed/declined → **owner's one-time solve** in that window (`plain-chrome show PORT TARGET`, or `pw-identity login <url>`), asked as one concrete line ("solve the slider on <site> in the window I opened"). After that, rungs 3–5 pass for that site (cookie ~1 year).

Never answer from other data because a site blocked you; name every site you could not read. Stop rules: helpers stop at the first non-200 and print `{"blocked": …}`; **404/410 = ad gone, skip**, not a block.

## Rules (each with why)
**Walls**
- What Akamai/DataDome catch is "Playwright launched this browser", not headed/headless or fresh/logged-in → plain-chrome; `--headless` loses it (e.g. mobile.de, lacentrale).
- Imperva catches Playwright **attached at all** (CDP `*.enable` domains) → never lane/identity/plain-chrome+Playwright on Imperva sites; http or Camoufox only. Why: once flagged, **every** agent browser on that IP gets the bot page for hours, often into the next day.
- Solve DataDome in plain-chrome, never in a lane: a correct slide in Playwright → "Access temporarily restricted".
- Never open a second browser on a site whose captcha is showing or was just solved; reuse it, close via `plain-chrome close` so the cookie reaches the jar (two browsers = two captchas).
- A bot cookie can itself be banned: a poisoned `datadome` in the jar blocks every browser. Test with `--fresh`; fresh passes → `plain-chrome cookies --delete <domain> <name>`. A `datadome` cookie in a profile does not prove a solve (blocked visits set one too).
- WAF home pages can be stricter than data URLs: don't warm up on `/` where the site row says so (e.g. marktplaats 403s on `/`); others need the home page first (lacentrale `--warm`).

**Pacing** (shared IP = shared budget)
- Before every load/api/phone/send/login on a classified: `carhunt pace take <site> <kind> [--via <CC>]` (Python `pace.acquire`). Exit 3 / `PaceExceeded` → stop and come back at `retry_at` (or `--wait` for a short gap), don't retry. Why: budgets are shared by all agents (e.g. coches ≤2 loads/rolling hour); an unpaced check silently eats a sender's slot.
- Bursts kill: leboncoin hard ban for hours after fast search bursts; coches 5th load at 10 s = bot page; mobile.de ~25 fast loads per profile, home IP 403 after ~41 sweep loads; custojusto 403 after ~50 ads at 6 s.
- Day caps (phone reveals, sends) are taken **before** the action and reset at local midnight; missing caps in site.yaml → conservative default.

**Identity**
- If it doesn't need a login, use a lane. Identity = **one step, then `browser_close`** (check the message, close; reveal the phone, close). Never probe it (`about:blank` "to check"), never hold it across a wait on the owner. Why: a parked holder blocks every other agent. A hook releases it after `browsers.idle_release_s` (180 s) idle anyway.
- Busy? The PreToolUse hook blocks with holder + free copies → switch to a free `ch-identity-x`; never wait, never force a holder off. `pw-identity pool` lists all.
- Google is **master-only** (`ch-identity`): Google logs out a session it sees in several profiles; the hook blocks Google URLs on copies.
- Only cookies sync between copies; a localStorage login must be made on the master. Copy lacks a session / API 401 with a stale token → `pw-identity seed --all`, not "blocked".
- Never sign Chrome itself in (Chrome Sync) on any agent profile.

**Accounts & secrets** — details: [references/logins-and-accounts.md](references/logins-and-accounts.md)
- Agents log in and sign up **themselves**; only a code that goes to the owner's phone goes to the owner, **batched** into one ask. Why: agents should not be blocked by anything they can do themselves.
- **Never print a credential** — not `cat`/`grep`/`head` on a secrets dir, not "masked". Read secrets only inside the script that types them; never snapshot/screenshot a sign-in page with a password typed. Why: anything printed lands in the transcript.
- Codes and confirm links: email first (`t0=$(date +%s)` before the site sends, then `carhunt email-code <site> --since $t0` [`--link REGEX`]; Python `accounts.wait_code` / `wait_link`), even for "texted" codes.
- Never type the owner's Google password for "Continue with Google" on a third-party site; use guest forms.
- Never fake domestic data a form demands (local mobile, postcode): stop and report.

**Proxies & SMS** — details: [references/proxies-and-sms.md](references/proxies-and-sms.md)
- Country IP only for steps the site row marks geo-gated (phone/send/login), never for general browsing. Why: paid per GB.
- Proxies **fail closed**: exit country verified before the first load; mismatch → `ProxyUnavailable`, no request leaves. Why: a dead tunnel can silently serve the home IP.
- One sticky session per run (a new IP per load → DataDome slider within a few loads). An account made on a country IP lives on that one IP forever; its profile never joins the identity pool.
- SMS rental only for **verify-once** sites (`carhunt sms policy <site>` must allow it: site.yaml `account.verification: sms-once`), never SMS-2FA-every-login sites, and only on the owner's OK (it's a purchase). Why: a rented number dies after one SMS → any later SMS challenge = lockout.

**Messaging (transport side)**
- **Never submit a test message to a real seller.** Test up to the filled form, then close that tab at once. Why: a filled form left open on a real ad can get sent. Real sends go through `carhunt say` (guards, caps, ledger), never a raw click.
- **Never press "Make an offer"** (or any price/offer button): a price commits the owner.
- Click send **once**; verify by the site's API answer (e.g. contact-mail 2xx), not UI text (differs per domain). "Not sent" can still arrive (an aborted XHR can deliver) → check sent box / relay mail before any re-send.
- Site quirks live in the site row (Enter resets coches.net's form; Wallapop truncates at 300 chars; off-screen windows need `el.evaluate(e => e.click())`).
- Confirm with the owner before anything else that commits: paying, ordering, accepting terms, changing account settings.

## Close what you open (every browser, every run)
- MCP (lane, identity): `browser_close` as the last browser step.
- `plain-chrome`: `plain-chrome close PORT TARGET` (clean close flushes cookies to the jar; a killed Chrome loses its last ~30 s of cookies).
- Scripts: `with tab(…)` / `try…finally`; one run = one tab. Tests: real browsers only behind `@pytest.mark.chrome`, closed in fixture teardown.
- **Never `pkill`/`killall` by pattern**: kill only your own pid / close your own PORT TARGET. Why: a pattern kill hits other agents' browsers. `browser-reaper` (kills only browsers carhunt started, by pid record) is a safety net, not a licence.
- Hand-off windows (captcha for the owner, OAuth): close once done. Screenshots go to `$CARHUNT_HOME/browsers/mcp-out/` or a scratch dir, never notes or the repo.

## Subagents
Subagents share the parent's MCP connections → give each browsing subagent its own lane `ch-lane-a`, `-b`, `-c`, `-d` in order (never the same one twice in one fan-out) and, for logged-in steps, its own `ch-identity-a…d`; the parent keeps `ch-lane` + `ch-identity` (and is the only one touching Google). Put it in the prompt: "Use the `ch-lane-b` browser tools for all browser work; `ch-identity-b` for logged-in steps; no other browser." Scripts use `pw-identity acquire <name> --any` / `tab("identity")` and get whichever copy is free.

## Troubleshooting
| symptom | fix |
|---|---|
| `mcp__ch-lane__*` / `mcp__ch-identity__*` tools missing | servers load at session start: `carhunt doctor`; `launchctl list \| grep carhunt.`; logs `$CARHUNT_HOME/browsers/logs/`. Restart: `pw-identity -b <browser> restart`, lanes: `launchctl kickstart -k gui/$(id -u)/carhunt.lanes` (kills every session's tabs on it) |
| "Browser is already in use" (identity) | another holder: `pw-identity status`; use a free copy; never force |
| lane: bot check / blank page / 403 | climb the ladder (identity → plain-chrome → plain on identity profile → solve → owner) |
| DataDome 403 + "slide right" on the first request | (a) Playwright launched it → plain-chrome passes; (b) IP flagged (fresh plain-chrome blocked too) → rung 6, else owner via `pw-identity login <url>` |
| every browser blocked on one DataDome site, `--fresh` passes | poisoned jar cookie → `plain-chrome cookies --delete <domain> datadome` |
| logged-in site API 401 / copy not logged in | stale pool token → `pw-identity seed --all` (not a block) |
| Imperva "bot" page on every agent browser | IP flag lasts hours: stop that site ≥2 h; never retry with another browser (each retry extends it) |
| "fuera de España" / contact API 403 from abroad | geo-gated: country proxy + camoufox per the site row, not a different browser |
| `ProxyUnavailable` | exit IP wrong/unverifiable → stop; `carhunt proxy test <CC>`; never fall back to the home IP |
| `PaceExceeded` | wait until `retry_at`; don't switch site helper or IP to dodge it |
| a filled form left open on a real ad | close the tab now, nothing else; report it |
| owner's Chrome won't open/quit, an agent profile shows in it | something launched the installed Chrome on an agent profile: `pw-identity -b <browser> release --force`, point it at `agent-chrome` |

More: [references/plain-chrome.md](references/plain-chrome.md) (Agent Chrome, plain-chrome, jar, captcha solver) · `docs/browsers.md` (install, config, commands).
