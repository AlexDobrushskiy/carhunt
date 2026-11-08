# browsers / access

Agent Chrome, MCP lanes + identity pool, plain-chrome, reaper, captcha, proxies, pacing, accounts. Agent rules (which browser, escalation ladder, per-site table): [`skills/carhunt-browsers/SKILL.md`](../skills/carhunt-browsers/SKILL.md).

Code: `browsers/bin/` (shell tools), `browsers/` (MCP + launchd templates), `carhunt/access/` (Python). State: `$CARHUNT_HOME/browsers/` (profiles, leases, pid records, jar, logs) — never in the repo.

## Commands

### Shell tools (`browsers/bin/`, on PATH after bootstrap)
| tool | does |
|---|---|
| `agent-chrome` | build/refresh the re-signed Chrome clone; prints its executable path |
| `serve <lanes\|identity\|identity-x>` | run one Playwright MCP server (launchd calls it) |
| `pw-identity [-b <browser>] status\|pool\|acquire\|release\|seed\|sync\|login\|reap\|restart\|hook pre\|post` | identity leases (one holder per browser), pool copies, cookie sync, manual login window |
| `plain-chrome fetch\|open\|close\|show\|hide\|status\|cookies [--delete D N]` (= `carhunt browser plain …`) | normal-launch Chrome, attach after first load; trust-cookie jar |
| `browser-reaper [--dry-run] [--max-age H] [--json]` (= `carhunt browser reap`) | kill only browsers carhunt started (pid record + matching cmdline) that are orphaned or older than H |

### `carhunt` groups
| command | does |
|---|---|
| `carhunt browser mcp-config [--claude\|--json\|--codex\|--hooks] [--scope user]` | print `claude mcp add` lines (default) / JSON / Codex TOML / a preview of the identity-lease hooks (`carhunt hooks install` merges them into `$CARHUNT_HOME/claude/settings.json`); bootstrap asks, then runs them |
| `carhunt browser launchd render\|install\|uninstall [--out D] [--dry-run]` | the `<launchd_prefix>*` jobs (macOS) |
| `carhunt browser site-table [--sites-dir D] [--write P] [--check P]` | render the skill's site table from `carhunt/sites/*/site.yaml`; `--check` exits 1 on drift (CI) |
| `carhunt browser geo status\|release <CC> [--force]` | country-exit browser lease (held by `session.tab(..., country=CC)` / `geo.lease`) |
| `carhunt proxy test <CC>` | exit IP country + type through the configured provider (no credentials printed) |
| `carhunt sms policy <site>` · `rent --site D --country CC --service ID [--pool P] [--dry-run]` | rented one-time numbers (policy below; exit 3 = refused) |
| `carhunt captcha solve (--plain\|--lane\|--identity[-x]\|--cdp URL) [--url P] [--target T]` · `stats` | local solver |
| `carhunt pace take <site> <kind> [--via CC] [--wait]` · `status [site]` · `reset-day <site> [kind]` | shared ledger + day caps; `kind` ∈ `load api phone send login`; exit 3 = refused (`retry_at` in the JSON) |
| `carhunt creds new <site> --user U\|- [--overwrite]` · `status <site>` | generate + store a site password (`site_<domain>_user/_pass`); prints secret names only; refuses to overwrite (exit 3) |
| `carhunt email-code <site> [--since EPOCH\|10m] [--timeout S] [--pattern RE \| --link RE] [--query Q]` | wait for the site's one-time code (or confirm link) in Gmail; prints only that; exit 1 = none in time, 2 = Gmail not set up |
| `carhunt doctor` | includes browser checks (Chrome, Node, servers up, ports free, Ollama if captcha on, proxy/SMS secrets if enabled) |

Python: `access.session.tab(route, country=, site=, fresh=)`, `access.pace.acquire(site, kind, via=)`, `access.jar.get(domain, name)` (read-only), `access.proxy.get(country, sticky_minutes)`, `access.creds.login(site)` / `creds.new(site, email)`, `access.accounts.wait_code(site, since=)` / `wait_link(site, since=, pattern=)`, `access.accounts.sms.policy(site)` / `rent(country, service, site=)` / `wait_code(rental)`. Errors: `Blocked(signature)`, `PaceExceeded(retry_at)`, `ProxyUnavailable`, `LeaseBusy`.

### `session.tab` handle
| | |
|---|---|
| browser routes | a Playwright sync Page: unknown attributes (locator, keyboard, context, url, content, wait_for_timeout, on…) go to the page; available after the first `goto` (plain-chrome/identity launch on that URL) |
| `goto(url, wait_until=, timeout=ms, paced=True)` | returns the HTTP status (0 = none); with `site`: takes a `load` slot (waits ≤180 s for a gap) and raises `Blocked` on a wall; `paced=False` when the caller already took the slot (sites' Net) |
| `fetch(url, …)` | in-page fetch (site's own API with the tab's cookies), paced + block-checked like goto |
| http route | goto / content / html / fetch / url / wait_for_timeout only |
| `fresh=True` | throwaway profile (plain-chrome without country); lane/camoufox/http are throwaway anyway; identity/geo refuse |
| camoufox | `main_world_eval` on: `page.evaluate("mw:…")` runs in the page's own JS world (coches.net XHR patch) |

### Pace ledger (`access.pace`)
| | |
|---|---|
| key | site.yaml `site` id, whatever the caller's spelling (dir name, domain, host) — one budget per site |
| `via=CC` | proxied request: own rate budget (`<site>@cc`), same day caps |
| `load` | site.yaml `pace{min_gap_s, max_loads_per_hour, max_loads_per_run, max_loads_per_day}` |
| `api` | JSON read, not a page load: `pace.api_min_gap_s` (default `min_gap_s`), `pace.max_api_per_hour`; no load caps |
| `phone` `send` `login` | `caps{<kind>_per_day, <kind>_per_hour, <kind>_min_gap_s}` |
| defaults | `pace` 12 s / 30 h / 60 run only for a site without a `pace` section; `caps` phone 5 · send 10 · login 3 per day unless the site sets them |

## Install (macOS, Apple Silicon)
| need | how | why |
|---|---|---|
| Google Chrome | normal install in `/Applications` | Agent Chrome is a re-signed clone of it |
| Node 22 | `brew install node@22` | Playwright MCP servers (`npm ci` in `browsers/`) |
| Python 3.12 venv | bootstrap (`pip install -e .`) | `carhunt.access` |
| Docker (optional) | Docker Desktop / colima | only for a VPN-in-container country exit (proxy provider is preferred) |
| Camoufox (optional) | `pip install camoufox && python -m camoufox fetch` | `camoufox` route: Imperva sites behind a country proxy |
| Ollama + VLM (optional) | `brew install ollama && ollama pull qwen3.5:4b`; OWLv2 downloads on first use (~GBs, PyTorch/MPS) | captcha image grids; sliders/checkboxes need no model. Tested on an M1 Max 32 GB |

`browsers/install [--yes] [--skip-launchd] [--skip-mcp] [--dry-run]` (bootstrap calls it) runs: `npm ci` → `agent-chrome` → launchd jobs (`<launchd_prefix>lanes`, `…identity`, `…identity-a…`, `…agent-chrome-refresh`, `…identity-seed`, `…browser-reaper`; `carhunt browser launchd install`) → MCP registration + hooks (asks) → `carhunt doctor`.

## First run
1. **Identity master login:** `pw-identity login https://<site>` opens a visible window on the master profile; sign in to Google (if you'll use it) and any site you want agents to share. Agents can do site logins themselves later; only Google + phone-code steps need you.
2. **Seed the pool:** `pw-identity seed --all` (APFS clones of the master minus Google cookies; a 6-hourly job reseeds stale idle copies).
3. **Trust-cookie jar:** fills itself: every plain-chrome close and identity launch harvests bot-check cookies. To prime a DataDome site: `plain-chrome fetch --warm https://<site>/ https://<site>/<deep-link>`; if a captcha shows, `carhunt captcha solve` or `plain-chrome show` and solve once.
4. **MCP:** `carhunt browser mcp-config` → review → run the lines (bootstrap asks first). Identity-lease hooks: `carhunt hooks install` ([orchestrate.md](orchestrate.md#guard-hooks-hookscarhunt_hookpy-stdlib-only)).
5. `carhunt doctor`.

## Coexistence with other browser setups
Ports and labels avoid the usual Playwright MCP / Chrome debug ports (8931/9331) and `com.<user>.*` labels:

| | default | config |
|---|---|---|
| MCP: lanes / identity / copy *i* | 18931 / 18932 / 18933+*i* | `browsers.ports.mcp_base` |
| Chrome debug: same offsets | 19331 / 19332 / 19333+*i* | `browsers.ports.debug_base` |
| plain-chrome debug | 19341 | `browsers.ports.plain_debug` |
| launchd labels | `carhunt.*` | `browsers.launchd_prefix` |
| MCP names | `ch-lane`, `ch-lane-a…`, `ch-identity`, `ch-identity-a…` | `browsers.mcp_name_prefix` |
| profiles, jar, logs | `$CARHUNT_HOME/browsers/` | `CARHUNT_HOME` |

`browser-reaper` only touches pids with a carhunt pid record, so it never kills other browsers.

## Proxy provider
- Needed only if your target sites gate steps by country (site rows with `country_ip`). Requirements: **residential**, country targeting, sticky sessions ≥ 30 min, HTTP(S) user:pass gateway, pay-as-you-go per GB.
- Supported: Decodo residential PAYG (adapter `decodo`); others untested — add an adapter in `carhunt/access/proxy.py`.
- `carhunt secret set proxy_credentials` → `net.proxy.provider: decodo` → `carhunt proxy test ES` (expect `country: ES`, residential). Fail-closed: a wrong/unknown exit raises `ProxyUnavailable` before any site request.
- Free VPNs (VPN Gate) and datacenter VPN ranges: don't (flagged on first load, messaging soft-blocked).

## SMS provider
- Only for sites that verify a phone **once** at signup and accept rented numbers. Enforced by `carhunt sms policy|rent --site`: allowed only when the site's `account.verification` is `sms-once`; `sms-own` (owner's own number), `sms-every-login` or unknown → refused (fail closed).
- Supported: SMSPool (adapter `smspool`, prepaid balance). Choose the pool by per-service success rate (cheap pools return recycled numbers).
- Site kinds: **verify-once, domestic-only** (e.g. leboncoin: FR mobile) → rent; **accept foreign numbers** (e.g. subito) → use your own; **SMS 2FA every login** (marktplaats/2dehands) → never rent, use your own or skip; **IP-gated activation** (kleinanzeigen) → open the link on mobile data.

## Site accounts (generic)
1. Check the site's `account` row in site.yaml (`needed_for`, `verification`, `note`, `mail_from`; values: [design.md](design.md#siteyaml-keys)).
2. From an identity copy (or the site's `geo` browser if the account must live on a country IP): sign up with `accounts.email` (+ `accounts.gmail.plus_address`), password from `carhunt creds new <site> --user <email>` / `creds.new` (never printed).
3. Codes: take `t0=$(date +%s)` before triggering the mail, then `carhunt email-code <site> --since $t0` (or `accounts.wait_code(site, since=t0)`); phone-only codes → one batched ask to the owner.
4. Set real name (+ photo where the web allows) — helps with private sellers.
5. Record any quirk (no SMS recovery, IP-bound, app-only fields) in the site's `site.yaml` notes.

## Config section
Keys live in `config.example.yaml` (`browsers`, `net`, `accounts`, `sites.overrides`); schema `carhunt/core/config.schema.json` is strict (unknown key = error).
| key | read by | note |
|---|---|---|
| `browsers.*` (ports, prefixes, pool sizes, captcha) | `access.settings`, `mcp`, `captcha` | defaults avoid 8931/9331 |
| `net.proxy.{provider, credentials, gateway, echo_url}` | `access.proxy` | sticky session = 30 min (Decodo's max); per site: `sites.overrides.<site>.proxy.sticky_minutes` or site.yaml `proxy.sticky_minutes` |
| `net.geo.<cc>.{tz, locale}` | `access.geo` | geo browser TZ/locale |
| `accounts.{email, sms, gmail}` | `accounts.*` | Gmail: read-only OAuth |
| `sites.overrides.<site>.{pace, caps, account, proxy, …}` | `access.pace`, sites | one level deep per section; key names as in site.yaml. Tighten only: site.yaml numbers are measured ceilings, e.g. `mobile.de: {pace: {min_gap_s: 20, max_loads_per_hour: 20}}` |

## macOS-only bits
APFS clones (`cp -c`) for Agent Chrome + pool seeding · `codesign` ad-hoc re-sign · launchd jobs · `open -g` + window positioning for plain-chrome · Keychain secrets backend · `--use-mock-keychain`. Linux would need systemd units, a non-clone Chrome path and plain copies.

## Gaps
- One proxy provider (Decodo) and one SMS provider (SMSPool) have adapters.
- Wall data is from a PT residential IP; which sites need which country IP depends on where you live.
- Identity leases are enforced by Claude Code hooks only; other agent CLIs must call `pw-identity acquire`.
- Tests: `pytest carhunt/access` (offline); real-Chrome tests are opt-in with `CARHUNT_TEST_CHROME=1`.
- Site limits drift; `measured` dates in site.yaml are the staleness signal.
- Captcha: hCaptcha image tasks unsupported.
