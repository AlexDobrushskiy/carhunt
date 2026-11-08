# carhunt design

Layout, module boundaries and the interfaces between them. Commands and config keys in full: each `docs/<module>.md` ([index](index.md)).

## Principles
- **Repo = code, templates, docs, synthetic fixtures.** Everything a run produces (config, secrets, DB, ledgers, rendered briefs, state, logs, browser profiles) lives in `$CARHUNT_HOME` (default `~/.carhunt`), never in the repo.
- **cardb is the hub.** Every stage reads/writes car facts through cardb (REST, or the `cardb` CLI). No module keeps its own car list.
- **One config file** (`$CARHUNT_HOME/config.yaml`, schema `carhunt/core/config.schema.json`, worked example `config.example.yaml`). The buyer profile lives there, not in code.
- **Secrets by name only.** Config holds `secret:NAME`; values come from the secrets backend. No command prints a value.
- **Rules live in code where they can.** Pace, caps, quiet hours, send guards, notify kinds are enforced by the tool, not by brief prose; each rule keeps a one-line why (incident + date).
- **Platform:** macOS (Apple Silicon) + agterm + Claude Code, the proven setup. Session and secrets backends are interfaces, so tmux or Linux can be added.

## Layout

| path | module | lang | what |
|---|---|---|---|
| `pyproject.toml`, `carhunt/cli.py`, `carhunt/core/`, `scripts/` | core | Py 3.12, sh | config, secrets, clock/quiet hours, locks, paths, notifier, cardb client, CLI dispatcher, doctor, bootstrap, privacy check |
| `cardb/`, `deploy/` | db | Go | listings DB server + CLI, ranking, compose file |
| `web/` | web | Astro/TS, Node 22 | phone-first UI over cardb |
| `browsers/`, `carhunt/access/`, `skills/carhunt-browsers/` | browsers | sh/Node/Py | agent Chrome, lanes, identity pool, plain-chrome, reaper, captcha, proxy, pace ledger, accounts, MCP config |
| `carhunt/sites/` | sites | Py | one plugin per marketplace (`<pkg>/plugin.py` + `site.yaml`), liveness |
| `carhunt/discover/`, `agents/roles/sweep/` | discover | Py | sweep runner, scope, normalize, ingest |
| `carhunt/contact/`, `skills/carhunt-outreach/`, `agents/roles/outreach/` | contact | Py | guarded send, channels, ledger, watcher, mail routing, asks |
| `carhunt/vet/`, `knowledge/`, `skills/carhunt-vet/`, `agents/roles/{vet,buy}/` | vetbuy | Py + md | VIN/registry/PR-code tools, evidence pack, vet/buy/import playbooks |
| `carhunt/orchestrate/`, `agents/templates/`, `agents/roles/{overseer,learning}/`, `hooks/` | orchestrate | Py + md | sessions (agterm), launch, state + handover, pause, digest, learning, schedule, guard hooks |
| `tests/`, `conftest.py` | — | Py | cross-module + e2e tests, root test isolation |

## CLI

`carhunt/cli.py` auto-discovers `carhunt/<pkg>/cli.py: register(subparsers)`; a plugin that fails to import prints a warning, the rest works. Doctor: `carhunt/<pkg>/doctor.py: checks() -> list[Check(name, status ok|warn|fail, detail, fix)]`; `carhunt doctor` runs all.

| package | groups |
|---|---|
| core | `config` (show, get, validate, path) · `secret` (set, ls, check, rm, exec) · `notify` (send, inbox, poll) · `doctor` |
| access | `browser` (mcp-config, launchd, identity, plain, reap, site-table, geo) · `pace` (status, take, reset-day) · `proxy test` · `sms` (policy, rent) · `email-code SITE` · `creds` (new, status) · `captcha` (solve, detect, bench, stats, slide-js) |
| sites | `site [SITE] search\|ad\|phone\|live\|info` (JSON lines; `carhunt site list`) · `liveness` |
| discover | `sweep [--sites a,b] [--window morning\|afternoon] [--dry-run] [--max N]` (exit 0 ok · 1 error · 3 blocked/capped · 10 refused) |
| contact | `say` (exit 0 sent · 10 refused · 11 failed · 12 unknown) · `watch` · `mailroute` · `ledger show\|reconcile` · `asks list\|close` |
| vet | `vin decode\|check-digit\|rdw\|prcodes` · `evidence CAR [--write-asks]` |
| orchestrate | `agent launch\|side\|ls\|screen\|ctx\|close` · `state get\|set\|add\|done\|takeover\|cleanup\|validate\|handover` · `msg` · `pause` · `unpause` · `digest` · `learn start\|collect` · `schedule install\|uninstall\|show` · `hooks install\|uninstall\|show\|statusline` |

`cardb` (Go binary) has its own CLI: `cardb --help`, [db.md](db.md).

## Interfaces

### core (`carhunt.core`) — [core.md](core.md)
- `config.load() -> Config` (`$CARHUNT_CONFIG` or `$CARHUNT_HOME/config.yaml`), schema-checked; `Config.get("a.b")`, `.secret("a.b")` resolves lazily, `.as_dict()` is safe to print.
- `secrets.get/set/exists/delete(name)`. Lookup: env `CARHUNT_SECRET_<NAME>` → backend `keychain` (service `carhunt`, default) · `op` · `file` (`$CARHUNT_HOME/secrets/NAME`, 0600).
- `clock.now()` in `owner.tz` (`CARHUNT_FAKE_NOW` for tests), `clock.in_window("21:30-09:30")`; `lock.flock(name)`; `paths.pause_file()`, `paths.agent_dir(role)`.
- `notify.send(text, agent=, kind=digest|ask|urgent)`: FYI is refused; quiet hours hold or silence. Replies routed into `$CARHUNT_HOME/agents/<agent>/inbox.jsonl`.
- `db.Client.from_config()`: thin cardb REST client; `ApiError` ⊃ `NotFound`, `Conflict`, `Unreachable`.

### cardb (`cardb/`) — [db.md](db.md)
- Contract: `cardb/api/openapi.yaml`. Buyer profile (tiers, hard filters, weights, families, options, home) read from `config.yaml` `owner` + `search`; no buyer constants in Go.
- **Ranking lives here only** (queue: tier, fair price per peer group, landed cost, score). Discover writes facts, never scores.
- `powertrain` block (BEV/PHEV/HEV/ICE); price sanity on write; `If-Match` on PATCH; `users` (owner + viewers) with per-user verdicts.
- `cardb profile check FILE`: validates a config's buyer profile offline, as the server would read it.
- `cardb init`: data dir `$CARHUNT_HOME/cardb/`, tokens into the secrets backend, hashes in `<data>/tokens`. Author: `CARDB_AUTHOR` (set per agent by launch), else token name. Exit codes 0/1/2/3, `--json` everywhere.

### access (`carhunt.access`, `browsers/bin/`) — [browsers.md](browsers.md)
- `session.tab(route, *, site=None, country=None, fresh=False)`: context manager; `route` ∈ `http | lane | identity | plain-chrome | camoufox`. Browser routes yield a Playwright-compatible Page; `goto(url, paced=True) -> int` (HTTP status, 0 = no response) paces and raises `Blocked` when `site` is given; `paced=False` when the caller took the slot. `country` → residential exit, verified fail-closed; `fresh` → throwaway profile; identity + country refuses.
- `pace.acquire(site, kind, *, via=None, wait=False)`: `kind` ∈ `load | api | phone | send | login`; `via` = proxy exit country (own rate budget, same day caps). Raises `PaceExceeded(retry_at)`. Shared across agents (SQLite ledger).
- `jar.get(domain, name)`: newest trust cookie from plain-chrome's jar (never logged).
- `proxy.get(country)` + `proxy.verify_exit`; `accounts.email_code(site, since, pattern)` / `wait_link`; `accounts.sms.policy(site)` / `rent` (owner OK per rental); `creds.login(site) -> (user, password)` via core secrets.
- Errors: `Blocked(signature)`, `PaceExceeded`, `ProxyUnavailable`, `LeaseBusy`.

### sites (`carhunt.sites`) — [sites.md](sites.md)
- `model.py`: `SearchQuery`, `Card`, `RawAd`, `Seller`, `Liveness`. `base.py`: `Site` protocol `search(q)`, `ad(url)`, `phone(ad, reveal=)`, `is_live(url)`; registry `get/ids/for_url`; `Gone`, `Unsupported`, `Blocked`.
- `carhunt/sites/fake/`: synthetic site, registered only with `CARHUNT_FAKE_SITES=1` (e2e).
- Site **senders** (marketplace chats) live in contact (`contact/channels/sites/`).

`site.yaml` keys (schema `carhunt/sites/site.schema.json`, overridable per site in config `sites.overrides`):

| key | values |
|---|---|
| `site`, `name`, `kind`, `countries`, `hosts`, `ad_id` | identity; `kind` ∈ marketplace \| aggregator \| vin-history |
| `wall`, `route`, `country_ip`, `tab_home`, `accept_language` | bot wall seen; lowest route that works |
| `pace` | `min_gap_s`, `max_loads_per_run`, `max_loads_per_hour`, `max_loads_per_day`, `api_min_gap_s`, `max_api_per_hour`, `fresh_profile_every`, `read_after`, `why` |
| `caps` | `<kind>_per_day\|_per_hour\|_per_session`, `<kind>_min_gap_s`, `why` (kind = load\|api\|phone\|send\|login) |
| `account` | `needed_for[]`, `verification` ∈ none \| email \| email-link \| email-code \| google \| sms-once \| sms-own \| sms-every-login, `note`, `mail_from` (Gmail query for `email-code`) |
| `phone` | page \| decode \| reveal \| reveal-login \| text-only \| none |
| `messaging`, `notes[]`, `measured` | how to reach a seller; dated evidence |
| `liveness` | `supported`, `mode` fetch\|goto, `gone_redirect/_text/_title`, `sold_text`, `proxy_country`, `evidence` |
| `cursor.strategy` | newest_id \| first_seen \| full (+ `why`) |
| `proxy.sticky_minutes` | sticky exit length |

### discover (`carhunt.discover`) — [discover.md](discover.md)
Config `search` → per-site query → cursor → scope filter → detail read → normalize (VAT, cash price, flags, power/drive/fuel, options) → `upsert_listing` + photos. Cursors `$CARHUNT_HOME/discover/cursors.json`. Serial per site, stop at first block.

### contact (`carhunt.contact`) — [contact.md](contact.md)
- `carhunt say --channel whatsapp|email|<site> (--car|--to) (--text|--text-file) [--opener|--nudge] [--approved] [--dry-run]`: one `flock` around guard → send → verify → ledger (`$CARHUNT_HOME/contact/ledger.jsonl`) → `cardb msg`.
- `carhunt watch`: WhatsApp (wacli), Gmail, site inboxes → cardb (verbatim) + agent inbox.
- Asks: vet writes cardb `ask` events (`carhunt evidence --write-asks`); outreach sends them and closes with `carhunt asks close` (`ask_answered`). Vet never messages sellers.

### orchestrate (`carhunt.orchestrate`) — [orchestrate.md](orchestrate.md)
- Session backend: `spawn, send, screen, ctx_percent, close, alive`; agterm (`agtermctl`, mailbox). Agent CLI `claude` (default) or `codex`.
- `carhunt agent launch ROLE [--var K=V]… [--successor-of ID]`: render `agents/templates/common.md` + role brief + learned rules → `$CARHUNT_HOME/agents/ROLE/brief.md`, init `state.json`, spawn with `CARHUNT_AGENT=ROLE`, `CARDB_AUTHOR=ROLE`. Unknown placeholder fails the launch. Role `BASE-VARIANT` without its own brief → `agents/roles/BASE/brief.md` with `{variant}` set (`outreach-home`, `outreach-abroad`: own state, inbox, caps). `$CARHUNT_HOME/roles/<role>/brief.md` overrides the repo's.
- Hooks: `carhunt hooks install` writes guards (secret-guard, send-guard, mailbox, identity lease) into `$CARHUNT_HOME/claude/settings.json`; launch passes it with `claude --settings` and refuses an unguarded claude agent. The user's global settings stay untouched (`--user` opts in).
- `state.json` (`agents/state.schema.json`): `active_agent, status, handover_from, handover_notes{…}, pending_owner[], open_issues[], cursors{}`. Handover at measured ctx ≥ `orchestrate.handover_ctx_pct` (50).
- Day on launchd (`carhunt schedule install`): sweep, unpause, digests, night pause + learning, cleanup.

## Config sections
`owner` (core) · `secrets` (core) · `notify` (core) · `cardb` (db) · `web` (web: `url`, checked by doctor) · `search` (db + discover) · `browsers`, `net`, `accounts` (browsers) · `sites` (sites) · `discover` · `contact` · `vet` · `orchestrate`. Unknown keys anywhere are errors (typo guard). Keys per section: the module doc's "Config" table.

## Tests
- Root `conftest.py` isolates every suite (`tests/`, `carhunt/<pkg>/tests`): temp `CARHUNT_HOME` per test, `CARHUNT_SECRETS_BACKEND=file`, inherited `CARHUNT_*`/`CARDB_*` env dropped, real Keychain blocked unless a test is marked `keychain` and `CARHUNT_TEST_KEYCHAIN=1`. It builds `cardb` so real-cardb tests run instead of skipping.
- Offline by default; real Chrome only under `-m chrome`. Commands and e2e: [testing.md](testing.md).

## Privacy
Run data in `$CARHUNT_HOME`, secrets in the backend, synthetic fixtures; `scripts/privacy-check` on every commit, `--history` before any push. [privacy.md](privacy.md).

## Decisions (open to change)
| # | decision | why | alternative |
|---|---|---|---|
| D1 | macOS + agterm only in v1 | only proven setup; agterm required anyway | tmux backend + Linux secrets later |
| D2 | `evdb` renamed `cardb`; EV fields moved into `powertrain` | the repo is for any used car | keep `evdb` name |
| D3 | Ranking only in cardb | one answer for web, CLI, agents | discover-side scoring |
| D4 | Secrets: env → Keychain (default) / 1Password / file | no plaintext in repo or config | keyring lib |
| D5 | One Python package with auto-discovered CLI groups | modules never edit a shared dispatcher | one script per tool |
| D6 | Telegram optional; digest/ask/urgent only, enforced in code | EV run: half the pushes were noise | prose-only rule |
| D7 | Skills shipped as `carhunt-*` and symlinked | don't clash with the user's own skills | copy into `~/.claude/skills` |
| D8 | Guard hooks in `$CARHUNT_HOME/claude/settings.json`, passed with `claude --settings` | guards bind carhunt agents only; the user's other sessions stay unchanged | global `~/.claude/settings.json` (`hooks install --user`) |
| D9 | Root `conftest.py` forces file secrets + temp home for every test | a module test run wrote synthetic items into the real Keychain (11-08) | per-package fixtures |
| D10 | `carhunt creds new\|status` and `carhunt email-code SITE` as CLI | agents drive the CLI; values never reach the transcript | agents call Python |
| D11 | `captcha` extra (torch) not in `all` | heavy; most sites never need the local model | in `all` |
| D12 | Strict config schema (unknown keys fail) per section | typo guard: a misspelled key would silently run on the default | open module sections |
| D13 | `outreach-home` / `outreach-abroad` as variants of one brief | one rule set, separate state, inbox and caps | two briefs |
