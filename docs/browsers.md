# browsers / access

Agent Chrome, MCP lanes + identity pool, plain-chrome, reaper, captcha, proxies, pacing, accounts. Agent rules (which browser, escalation ladder, per-site table): [`skills/carhunt-browsers/SKILL.md`](../skills/carhunt-browsers/SKILL.md). Wall evidence per site: [`browsers/site-walls.md`](browsers/site-walls.md).

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
| `carhunt browser mcp-config [--claude\|--json\|--codex\|--hooks] [--scope user]` | print `claude mcp add` lines (default) / JSON / Codex TOML / the identity-lease hooks for settings.json; bootstrap asks, then runs them |
| `carhunt browser launchd render\|install\|uninstall [--out D] [--dry-run]` | the `<launchd_prefix>*` jobs (macOS) |
| `carhunt browser site-table [--sites-dir D] [--write P] [--check P]` | render the skill's site table from `carhunt/sites/*/site.yaml`; `--check` exits 1 on drift (CI) |
| `carhunt browser geo up\|status\|down <CC>` | leased single browser on its own profile behind a country exit |
| `carhunt proxy test <CC>` | exit IP country + type through the configured provider (no credentials printed) |
| `carhunt sms policy <site>` · `rent --site D --country CC --service ID [--pool P] [--dry-run]` | rented one-time numbers (policy below; exit 3 = refused) |
| `carhunt captcha solve (--cdp URL --target T \| --lane --url P \| --identity N --url P \| --open URL)` · `stats` | local solver |
| `carhunt pace take <site> <kind> [--via CC] [--wait]` · `status [site]` · `reset-day <site> [kind]` | shared ledger + day caps; `kind` ∈ `load phone send login`; exit 3 = refused (`retry_at` in the JSON) |
| `carhunt doctor` | includes browser checks (Chrome, Node, servers up, ports free, Ollama if captcha on, proxy/SMS secrets if enabled) |

Python: `access.session.tab(route, country=, site=)`, `access.pace.acquire(site, kind)`, `access.proxy.get(country, sticky_minutes)`, `access.creds.login(site)` / `creds.new(site, email)`, `access.accounts.wait_code(site, since=)` / `wait_link(site, since=, pattern=)`, `access.accounts.sms.policy(site)` / `rent(country, service, site=)` / `wait_code(rental)`. Errors: `Blocked(signature)`, `PaceExceeded(retry_at)`, `ProxyUnavailable`, `LeaseBusy`.

## Install (macOS, Apple Silicon)
| need | how | why |
|---|---|---|
| Google Chrome | normal install in `/Applications` | Agent Chrome is a re-signed clone of it |
| Node 22 | `brew install node@22` | Playwright MCP servers (`npm ci` in `browsers/`) |
| Python 3.12 venv | bootstrap (`pip install -e .`) | `carhunt.access` |
| Docker (optional) | Docker Desktop / colima | only for a VPN-in-container country exit (proxy provider is preferred) |
| Camoufox (optional) | `pip install camoufox && python -m camoufox fetch` | `camoufox` route: Imperva sites behind a country proxy |
| Ollama + VLM (optional) | `brew install ollama && ollama pull qwen3.5:4b`; OWLv2 downloads on first use (~GBs, PyTorch/MPS) | captcha image grids; sliders/checkboxes need no model. Measured on M1 Max 32 GB; smaller Macs unknown |

Bootstrap runs: `npm ci` → `agent-chrome` → launchd jobs (`<launchd_prefix>lanes`, `…identity`, `…identity-a…`, `…agent-chrome-refresh`, `…identity-seed`, `…browser-reaper`; `carhunt browser launchd install`) → MCP registration + hooks (asks) → `carhunt doctor`.

## First run
1. **Identity master login:** `pw-identity login https://<site>` opens a visible window on the master profile; sign in to Google (if you'll use it) and any site you want agents to share. Agents can do site logins themselves later; only Google + phone-code steps need you.
2. **Seed the pool:** `pw-identity seed --all` (APFS clones of the master minus Google cookies; a 6-hourly job reseeds stale idle copies).
3. **Trust-cookie jar:** fills itself: every plain-chrome close and identity launch harvests bot-check cookies. To prime a DataDome site: `plain-chrome fetch --warm https://<site>/ https://<site>/<deep-link>`; if a captcha shows, `carhunt captcha solve` or `plain-chrome show` and solve once.
4. **MCP:** `carhunt browser mcp-config` → review → run the lines (bootstrap asks first). `carhunt browser mcp-config --hooks` → merge into `~/.claude/settings.json` (identity leases).
5. `carhunt doctor`.

## Coexistence with an existing personal browser stack
Ports and labels are chosen not to collide with a typical personal setup on 8931/9331 and `com.<user>.*`:

| | default | config |
|---|---|---|
| MCP: lanes / identity / copy *i* | 18931 / 18932 / 18933+*i* | `browsers.ports.mcp_base` |
| Chrome debug: same offsets | 19331 / 19332 / 19333+*i* | `browsers.ports.debug_base` |
| plain-chrome debug | 19341 | `browsers.ports.plain_debug` |
| launchd labels | `carhunt.*` | `browsers.launchd_prefix` |
| MCP names | `ch-lane`, `ch-lane-a…`, `ch-identity`, `ch-identity-a…` | `browsers.mcp_name_prefix` |
| profiles, jar, logs | `$CARHUNT_HOME/browsers/` | `CARHUNT_HOME` |

`browser-reaper` only touches pids with a carhunt pid record, so it never kills the other stack's browsers.

## Proxy provider
- Needed only if your target sites gate steps by country (site rows with `country_ip`). Requirements: **residential**, country targeting, sticky sessions ≥ 30 min, HTTP(S) user:pass gateway, pay-as-you-go per GB.
- Proven: Decodo residential PAYG (adapter `decodo`); others untested — add an adapter in `carhunt/access/proxy.py`.
- `carhunt secret set proxy_credentials` → `net.proxy.provider: decodo` → `carhunt proxy test ES` (expect `country: ES`, residential). Fail-closed: a wrong/unknown exit raises `ProxyUnavailable` before any site request.
- Free VPNs (VPN Gate) and datacenter VPN ranges: don't (flagged on first load / soft-blocked messaging, 11-02/05).

## SMS provider
- Only for sites that verify a phone **once** at signup and accept rented numbers. Enforced by `carhunt sms policy|rent --site`: allowed only when the site's `account.verification` is `sms-once`; `sms-every-login` or unknown → refused (fail closed).
- Proven: SMSPool (adapter `smspool`, prepaid balance). Choose the pool by per-service success rate (cheap pools return recycled numbers).
- Site kinds: **verify-once, domestic-only** (e.g. leboncoin: FR mobile) → rent; **accept foreign numbers** (e.g. subito) → use your own; **SMS 2FA every login** (marktplaats/2dehands) → never rent, use your own or skip; **IP-gated activation** (kleinanzeigen) → open the link on mobile data.

## Site accounts (generic)
1. Check the site row (`account.needed_for`, `verification`).
2. From an identity copy (or the site's `geo` browser if the account must live on a country IP): sign up with `accounts.email` (+ `accounts.gmail.plus_address`), password from `creds.new(<domain>, <email>)` (never printed).
3. Codes: `accounts.wait_code(site, since=t0)`; phone-only codes → one batched ask to the owner.
4. Set real name (+ photo where the web allows) — helps with private sellers.
5. Record any quirk (no SMS recovery, IP-bound, app-only fields) in the site's `site.yaml` notes.

## Config section
Merge into `config.example.yaml` (replaces the current `browsers` / `net` / `accounts` stubs; adds `sites.overrides`):
```yaml
browsers:
  chrome_app: /Applications/Google Chrome.app
  lanes: 4                    # named lane registrations ch-lane-a… (one isolated server)
  identity_pool: 4            # logged-in profile copies ch-identity-a…
  headless: true              # MCP servers; plain-chrome is always headed (off-screen)
  ports: {mcp_base: 18931, debug_base: 19331, plain_debug: 19341}   # clear of a personal stack on 8931/9331
  launchd_prefix: carhunt.
  mcp_name_prefix: ch-        # MCP names ch-lane, ch-lane-a…, ch-identity, ch-identity-a… (identity hooks match these)
  idle_release_s: 180         # identity lease released + browser closed after this idle
  reaper_max_age_h: 6         # throwaway browsers older than this count as leaked
  captcha:
    enabled: false            # image grids need Ollama + a VLM (GBs)
    model: qwen3.5:4b
    ollama_url: http://127.0.0.1:11434

net:
  proxy:
    provider: none            # decodo | none
    credentials: secret:proxy_credentials
    sticky_minutes: 30        # one sticky exit per run

accounts:
  email: you@example.com      # site signups; codes are read from this mailbox
  sms: {provider: none, api_key: secret:sms_api_key}   # smspool | none; each rental needs the owner's OK
  gmail: {oauth_client: secret:gmail_oauth_client, token: secret:gmail_token, plus_address: cars}

sites:
  overrides:                  # per-site tweaks on top of carhunt/sites/<site>/site.yaml
    mobile.de: {pace: {min_gap_s: 15}}
```

## macOS-only bits
APFS clones (`cp -c`) for Agent Chrome + pool seeding · `codesign` ad-hoc re-sign · launchd jobs · `open -g` + window positioning for plain-chrome · Keychain secrets backend · `--use-mock-keychain`. Linux would need systemd units, a non-clone Chrome path and plain copies.

## Gaps
- Only one proxy provider (Decodo) and one SMS provider (SMSPool) measured; costs per site per month unknown beyond one campaign (66 MB ≈ $0.33).
- All wall measurements are from one PT residential IP; which sites need which country IP depends on where you live.
- Identity leases are enforced by Claude Code hooks only; other agent CLIs must call `pw-identity acquire`.
- Site limits drift (mobile.de tightened three times in two weeks); `measured` dates in site.yaml are the staleness signal.
- Captcha VLM benchmarked on one machine; hCaptcha image tasks unsupported.
