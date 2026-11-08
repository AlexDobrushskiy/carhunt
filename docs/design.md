# carhunt design

Layout, module boundaries and the interfaces between them. Commands and config keys in full: each `docs/<module>.md` ([index](index.md)).

## Principles
- **Repo = code, templates, docs.** Everything a run produces (config, secrets, DB, ledgers, rendered briefs, state, logs, browser profiles) lives in `$CARHUNT_HOME` (default `~/.carhunt`), never in the repo.
- **cardb is the hub.** Every stage reads/writes car facts through cardb (REST, or the `cardb` CLI). No module keeps its own car list.
- **One config file** (`$CARHUNT_HOME/config.yaml`, schema `carhunt/core/config.schema.json`, worked example `config.example.yaml`). The buyer profile lives there, not in code.
- **Secrets by name only.** Config holds `secret:NAME`; values come from the secrets backend. No command prints a value.
- **Rules live in code where they can.** Pace, caps, quiet hours, send guards, notify kinds are enforced by the tool, not by brief prose; each rule keeps a one-line why.
- **Platform:** macOS (Apple Silicon) + agterm + Claude Code. Session and secrets backends are interfaces, so tmux or Linux can be added.

## Layout
Module → paths → doc: [README](../README.md#modules). Role briefs per module: [agents/roles](../agents/roles/README.md); skills: [skills](../skills/README.md). Languages: Python 3.12 (`carhunt/`), Go (`cardb/`), Astro/TS on Node 22 (`web/`), sh + Node (`browsers/`).

## CLI

One `carhunt` command; each package plugs in its groups and doctor checks ([plugin contract](core.md#plugin-contract-other-modules)). Options and exit codes: `carhunt <group> --help` and the module doc.

| package | groups | doc |
|---|---|---|
| core | `config` (show, get, validate, path) · `secret` (set, ls, check, rm, exec) · `notify` (send, inbox, poll) · `doctor` | [core](core.md) · [secrets](secrets.md) · [notify](notify.md) |
| access | `browser` (mcp-config, launchd, identity, plain, reap, site-table, geo) · `pace` · `proxy test` · `sms` · `email-code SITE` · `creds` · `captcha` | [browsers](browsers.md#commands) |
| sites | `site [SITE] search\|ad\|phone\|live\|info` (`carhunt site list`) · `liveness` | [sites](sites.md#commands) |
| discover | `sweep` | [discover](discover.md#commands) |
| contact | `say` · `watch` · `mailroute` · `ledger` · `asks` | [contact](contact.md#commands) |
| vet | `vin decode\|check-digit\|rdw\|prcodes` · `evidence` | [vetbuy](vetbuy.md#commands) |
| orchestrate | `agent` · `state` · `msg` · `pause` · `unpause` · `digest` · `learn` · `schedule` · `hooks` | [orchestrate](orchestrate.md#commands) |
| cardb (Go) | `cardb --help` (own binary: server + client) | [db](db.md#api-and-cli) |

## Interfaces

Who calls whom. Signatures and details live in the module doc linked on each line.

- **Everything → core** (`carhunt.core`): config (`secret:NAME` refs resolved lazily), secrets, owner-tz clock, `flock`, paths, `notify.send(kind=digest|ask|urgent)`, `db.Client` for cardb. [core.md](core.md#python-api-carhuntcore)
- **Everything → cardb** over REST (`cardb/api/openapi.yaml`) or the `cardb` CLI; author = `CARDB_AUTHOR` (set per agent by launch). Buyer profile = config `owner` + `search`; **ranking only in cardb**, others write facts. [db.md](db.md)
- **sites, contact senders → access**: `session.tab(route, site=, country=, fresh=)` (Playwright-compatible page, `goto` → HTTP status, paced + `Blocked` when `site` is set), `pace.acquire(site, kind, via=)` with kinds `load | api | phone | send | login`, `jar.get`, `proxy`, `creds`, `accounts`. [browsers.md](browsers.md#sessiontab-handle)
- **discover, liveness → sites**: `Site.search/ad/phone/is_live` → `Card`, `RawAd`, `Liveness`; `Blocked` stops a site, `Gone` skips an ad. `carhunt/sites/fake/` (with `CARHUNT_FAKE_SITES=1`) for e2e. [sites.md](sites.md#python-interface-discover-contact-vet)
- **vet → contact** through cardb only: vet writes `ask` events (`carhunt evidence --write-asks`), outreach sends them and closes with `carhunt asks close` (`ask_answered` + fact). Vet never messages sellers. [contact.md](contact.md#commands) · [vetbuy.md](vetbuy.md#evidence-pack)
- **Every send → `carhunt say`** (one lock: guard → send → verify → ledger → cardb); the `send-guard` hook blocks other send paths. [contact.md](contact.md#guard-rules-order-and-why)
- **orchestrate → agents**: `carhunt agent launch ROLE [--var K=V]… [--successor-of ID]` renders `agents/templates/common.md` + role brief into `$CARHUNT_HOME/agents/ROLE/`; role `BASE-VARIANT` without its own brief → `agents/roles/BASE/brief.md` with `{variant}`. Guard hooks live in `$CARHUNT_HOME/claude/settings.json`, passed with `claude --settings`. Session backend = agterm. [orchestrate.md](orchestrate.md)

### site.yaml keys
Schema `carhunt/sites/site.schema.json`; per-site overrides in config `sites.overrides`. Read by sites (transport), access (pace ledger, site table), discover (cursor, `read_after`), contact (messaging).

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

Semantics: pace ledger [browsers.md](browsers.md#pace-ledger-accesspace), cursors [sites.md](sites.md#cursors-and-price-changes).

## Config sections
`owner`, `secrets`, `notify`, `cardb`, `web` (core) · `search` (db + discover) · `browsers`, `net`, `accounts` (browsers) · `sites` · `discover` · `contact` · `vet` · `orchestrate`. Values: [`config.example.yaml`](../config.example.yaml); what each key does: the module doc's "Config" section. Unknown keys anywhere are errors (D12).

## Tests
Every suite is offline and isolated by the root `conftest.py` (D9): [testing.md](testing.md). Commits pass `scripts/privacy-check` (git hook).

## Decisions (open to change)
| # | decision | why | alternative |
|---|---|---|---|
| D1 | macOS + agterm only | agterm required anyway | tmux backend + Linux secrets later |
| D2 | Powertrain-specific fields (EV battery etc.) under `powertrain` | any used car, not one type | flat EV columns |
| D3 | Ranking only in cardb | one answer for web, CLI, agents | discover-side scoring |
| D4 | Secrets: env → Keychain (default) / 1Password / file | no plaintext in repo or config | keyring lib |
| D5 | One Python package with auto-discovered CLI groups | modules never edit a shared dispatcher | one script per tool |
| D6 | Telegram optional; digest/ask/urgent only, enforced in code | unbounded pushes turn into noise | prose-only rule |
| D7 | Skills shipped as `carhunt-*` and symlinked | don't clash with the user's own skills | copy into `~/.claude/skills` |
| D8 | Guard hooks in `$CARHUNT_HOME/claude/settings.json`, passed with `claude --settings` | guards bind carhunt agents only; the user's other sessions stay unchanged | global `~/.claude/settings.json` (`hooks install --user`) |
| D9 | Root `conftest.py` forces file secrets + temp home for every test | a test must never reach the real Keychain or home | per-package fixtures |
| D10 | `carhunt creds new\|status` and `carhunt email-code SITE` as CLI | agents drive the CLI; values never reach the transcript | agents call Python |
| D11 | `captcha` extra (torch) not in `all` | heavy; most sites never need the local model | in `all` |
| D12 | Strict config schema (unknown keys fail) per section | typo guard: a misspelled key would silently run on the default | open module sections |
| D13 | `outreach-home` / `outreach-abroad` as variants of one brief | one rule set, separate state, inbox and caps | two briefs |
