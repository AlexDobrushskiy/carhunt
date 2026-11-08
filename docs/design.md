# carhunt design

Reference for builders and the integrator.

## Principles
- **Repo = code, templates, docs, synthetic fixtures.** Everything a run produces (config, secrets, DB, ledgers, rendered briefs, state, logs, browser profiles) lives in `$CARHUNT_HOME` (default `~/.carhunt`), never in the repo.
- **cardb is the hub.** Every stage reads/writes car facts through cardb (REST, or the `cardb` CLI). No module keeps its own car list.
- **One config file** (`$CARHUNT_HOME/config.yaml`, schema = `config.example.yaml`). The user's buyer profile lives there, not in code.
- **Secrets by name only.** Config holds `secret:NAME` references; values come from the secrets helper. Nothing prints a secret.
- **Lessons ship with their why.** Each rule ported from the EV run keeps a one-line reason (incident + date) in the module doc or skill.
- **Platform:** macOS (Apple Silicon) + agterm + Claude Code. That is what was proven. Linux is out of scope for v1. The session backend and secrets backend are interfaces, so tmux or Linux can be added later.

## Layout and owners

| path | module (builder) | lang | what |
|---|---|---|---|
| `pyproject.toml`, `carhunt/__init__.py`, `carhunt/cli.py`, `carhunt/core/` | **core** | Py 3.12 | config, secrets, clock/quiet hours, locks, paths, notifier, cardb client, CLI dispatcher, doctor framework |
| `scripts/bootstrap`, `scripts/doctor` | **core** | sh/Py | clone → first sweep |
| `cardb/`, `deploy/` | **db** | Go 1.26 | listings DB server + CLI (port of ev-listings), compose file |
| `web/` | **web** | Astro 5/TS, Node 22 | phone-first UI over cardb |
| `browsers/`, `carhunt/access/`, `skills/carhunt-browsers/` | **browsers** | sh/Node/Py | agent Chrome, lanes, identity pool, plain-chrome, reaper, captcha, proxy, pace ledger, accounts (email codes, SMS), MCP config |
| `carhunt/sites/` | **sites** | Py | one plugin per marketplace (`<site>/plugin.py` + `site.yaml`), liveness checker |
| `carhunt/discover/`, `agents/roles/sweep/` | **discover** | Py | sweep runner, criteria scope, normalize, ingest to cardb |
| `carhunt/contact/`, `skills/carhunt-outreach/`, `agents/roles/outreach/` | **contact** | Py | guarded send (`carhunt say`), channels, ledger, watcher, mail routing |
| `carhunt/vet/`, `knowledge/`, `skills/carhunt-vet/`, `agents/roles/{vet,buy}/` | **vetbuy** | Py + md | VIN/registry/PR-code tools, evidence pack, vet/buy/import playbooks |
| `carhunt/orchestrate/`, `agents/templates/`, `agents/roles/{overseer,learning}/`, `hooks/` | **orchestrate** | Py + md | sessions (agterm), state + handover, launch, pause, digest, learning, schedule, guard hooks |
| `README.md`, `docs/index.md`, `tests/e2e/` | **integrator** | | merge, docs index, clean-HOME bootstrap test, privacy audit |
| `docs/<module>.md` | each module | md | lean module doc: commands, rules + why, config keys |

A builder edits only paths it owns. Need a change elsewhere? Note it in your report (`handover_notes.cross_module`); the integrator or owner applies it. Shared files with expected small conflicts: `pyproject.toml` deps (core pre-declares; others append under their extra), `config.example.yaml` (core owns; others send their section in `docs/<module>.md` → integrator merges), `.gitignore`.

## Build order / dependencies

| module | can start | needs from others |
|---|---|---|
| core | now | — (**merges to main itself** when green, so others can `git merge main`) |
| db | now | — (commit `cardb/api/openapi.yaml` changes first) |
| browsers | now | core (secrets, config) |
| contact | now | core; cardb CLI/API (spec below); access session interface (spec below) |
| vetbuy | now | core (light) |
| orchestrate | now | core |
| sites | after browsers pushes `carhunt/access/session.py` + `pace.py` (or now, against the spec) | browsers, core |
| web | after db's openapi rename commit | db |
| discover | after sites pushes `carhunt/sites/model.py` + `base.py` | sites, core, db |

Until a dependency is merged, code against the interface below and use a fake in tests. Read other branches with `git show mod/<x>:<path>`.

## Interfaces

### Python CLI: `carhunt <group> …`
`carhunt/cli.py` (core) auto-discovers `carhunt/<pkg>/cli.py` that exposes `register(subparsers)`. No module edits `carhunt/cli.py`.
Groups: `config secret notify doctor` (core) · `browser proxy sms captcha pace` (browsers) · `site liveness` (sites) · `sweep` (discover) · `say watch mailroute ledger` (contact) · `vin evidence` (vetbuy) · `agent state msg pause unpause digest learn schedule hooks` (orchestrate).
Doctor: each package may expose `carhunt/<pkg>/doctor.py: checks() -> list[Check]` (`Check(name, status: ok|warn|fail, detail, fix)`). `carhunt doctor` runs all.

### core (`carhunt.core`)
- `config.load() -> Config` reads `$CARHUNT_CONFIG` or `$CARHUNT_HOME/config.yaml`, validates against `carhunt/core/config.schema.json`, resolves `secret:NAME` lazily. `config.home()`, `config.path(*parts)` (creates parents).
- `secrets.get(name)`, `secrets.set(name, value)`, `secrets.exists(name)`. Lookup: env `CARHUNT_SECRET_<NAME>` → configured backend: `keychain` (macOS `security`, service `carhunt`, account NAME; default) · `op` (1Password `op read`) · `file` (`$CARHUNT_HOME/secrets/NAME`, 0600). CLI: `carhunt secret set NAME` (no-echo prompt or stdin), `ls` (names only), `check NAME`, `exec NAME[=ENVVAR]… -- cmd`. **There is no command that prints a value.**
- `clock.now()` (tz = `owner.tz`; `CARHUNT_FAKE_NOW` for tests), `clock.in_window("09:30-21:30")`.
- `lock.flock(name)` (file lock under `$CARHUNT_HOME/locks/`).
- `paths.pause_file()` = `$CARHUNT_HOME/PAUSE`; `paths.agent_dir(role)`.
- `notify.send(text, *, agent, kind, buttons=None) -> ref|None`: `kind` ∈ `digest | ask | urgent`; FYI is refused by design (EV lesson: 14/28 pushes asked nothing). Quiet hours → silent or held. Backends: `telegram` (bot token + chat id), `stdout`, `none`. Inbound: `notify.inbox(agent).list/wait/ack` — Telegram replies routed by reply-to message id into `$CARHUNT_HOME/agents/<agent>/inbox.jsonl`.
- `db.Client.from_config()`: thin REST client for cardb (`upsert_listing, find_listing, car, cars, queue, status, fact, opt, event, msg, msgs, photo_add, listing_patch, verdict`). Raises `NotFound`, `ApiError`.

### cardb (Go, `cardb/`)
Port of ev-listings; contract = `cardb/api/openapi.yaml`. Changes:
- Renames: `needs_<owner>`→`needs_owner`, `km_to_<home>`→`distance_km`, author `<owner>`→`owner.name` from config, binary `evdb`→`cardb`.
- Buyer profile from `config.yaml` (`owner`, `search` sections): queue tiers, hard filters, trim weights, model families, option keys, home location. No buyer constants in Go.
- `powertrain` block (fuel BEV/PHEV/HEV/ICE, battery kWh, engine cc, gearbox); health facts per powertrain.
- **Ranking lives here only** (queue: fair price per peer group, landed cost, score). Discover writes facts, never scores.
- Price sanity on write (reject ×100, flag net vs gross); `If-Match` version on PATCH; add/remove ops for list fields.
- `users` (owner + viewers) with per-user verdicts.
- `cardb init` (data dir `$CARHUNT_HOME/cardb/`, token generated → stored via the secrets backends, client config). Token lookup mirrors core.secrets: env `CARHUNT_SECRET_CARDB_TOKEN` → Keychain `carhunt/cardb_token` → file.
- Author: `CARDB_AUTHOR` env (set per agent session by `carhunt agent launch`), else token name.
- Exit codes unchanged (0/1/2/3), `--json` everywhere.
- `deploy/compose.yaml`: cardb + web on localhost, data volume = `$CARHUNT_HOME/cardb`.

### access (`carhunt.access`, `browsers/bin/`)
- Shell tools on PATH after bootstrap: `agent-chrome`, `pw-identity` (lease/release/login/pool), `plain-chrome`, `browser-reaper`, `serve` (MCP servers).
- `access.session.tab(route, *, country=None, site=None)`: context manager yielding a page handle. `route` ∈ `http | lane | identity | plain-chrome | camoufox`. `country` → residential proxy with a fail-closed exit-IP check.
- `access.pace.acquire(site, kind)`: `kind` ∈ `load | phone | send | login`, shared across agents (ledger + day caps from `site.yaml`). Raises `PaceExceeded`.
- `access.proxy.get(country, sticky_minutes)` → proxy URL (provider adapter; Decodo first).
- `access.accounts.email_code(site, since, pattern)`, `access.accounts.sms.rent(country, service)` (policy: only for verify-once sites).
- `access.creds.login(site) -> (user, password)` via core.secrets (`site_<domain>_user/_pass`).
- Exceptions: `Blocked(signature)`, `PaceExceeded`, `ProxyUnavailable`.

### sites (`carhunt.sites`)
- `sites/model.py`: `SearchQuery`, `Card` (url, site, site_ref, title, price, km, year, seller_type, thumb), `RawAd` (normalized spec fields + raw json + photos + phones + seller).
- `sites/base.py`: `Site` protocol: `search(q) -> Iterator[Card]`, `ad(url) -> RawAd`, optional `phone(ad)`, `is_live(url) -> Liveness(state live|removed|unknown, evidence)`. Raises `Blocked`, `Gone`.
- `sites/<site>/site.yaml`: `wall`, `route`, `country_ip`, `pace{min_gap_s, max_loads_per_run}`, `caps{phone_per_day, send_per_day}`, `account{needed_for[], verification}`, `messaging`, `measured: <date>`, `notes`. The browsers skill renders its site table from these.
- `carhunt site <name> search|ad|phone|live` (JSON lines). `carhunt liveness` writes ad status only through `PATCH /listings/{id}` + `ad_check` event.
- `carhunt/sites/fake/`: synthetic site (bundled fixtures, no network), registered only with `CARHUNT_FAKE_SITES=1`, for e2e tests.
- Site **senders** (marketplace chat) live in contact (`contact/channels/sites/`), using `access.session`.

### discover (`carhunt.discover`)
`carhunt sweep [--sites a,b] [--window morning|afternoon] [--dry-run] [--max N]`: criteria from config `search` → per-site query → normalize (VAT net→gross, cash price, lease/damage keywords, power/drive inference, option regexes per language) → scope filter → `db.upsert_listing` + photos (`photo add --listing`, resolve later writes by URL). Cursors in `$CARHUNT_HOME/discover/cursors.json`. Serial per site, reads after sends, stop at first block.

### contact (`carhunt.contact`)
- `carhunt say --channel whatsapp|email|<site> (--car URL|ID | --to ADDR) (--text T | --text-file F) [--opener] [--nudge] [--dry-run]`. Pipeline under one `flock`: guard (PAUSE, quiet hours, opener window, per-channel caps/spacing, duplicate, no-URL, allow-list) → adapter.send → verify → append ledger (`$CARHUNT_HOME/contact/ledger.jsonl`) → `db.msg`. Exit: 0 sent · 10 refused (reason on stderr) · 11 failed · 12 unknown delivery.
- `carhunt watch`: one watcher for WhatsApp (wacli), Gmail, site inboxes → `db.msg` (verbatim, original language) + agent inbox line.
- `carhunt mailroute`: car mail out of the main inbox (plus-address, label).
- Asks from vet: cardb event `type=ask` (`summary` = question, `data.topic`); outreach agents send them and close with an `ask_answered` event.

### orchestrate (`carhunt.orchestrate`)
- Session backend interface: `spawn(name, cwd, cmd, env) -> id`, `send(id, text)`, `screen(id)`, `ctx_percent(id)`, `close(id)`, `alive(id)`. Backend: agterm (`agtermctl`, mailbox). Agent CLI: `claude` (default) or `codex`, from config.
- `carhunt agent launch ROLE [--successor-of ID]`: render `agents/templates/common.md` + `agents/roles/ROLE/brief.md` with config → `$CARHUNT_HOME/agents/ROLE/brief.md`, init `state.json`, spawn with `CARDB_AUTHOR=ROLE`.
- `state.json` schema (`agents/state.schema.json`): `active_agent, status (running|completed|paused|failed), handover_from, handover_notes{open_threads, unanswered_inbound, pending_sends, scheduled, promises, cross_module}, pending_owner[], open_issues[], cursors{}`. `carhunt state get|set|handover`.
- Handover at measured context ≥ `orchestrate.handover_ctx_pct` (default 50).
- `carhunt pause|unpause` (PAUSE file), `carhunt digest`, `carhunt learn` (night lessons → proposed rule edits), `carhunt schedule install` (launchd from `orchestrate.schedule`), `carhunt hooks install` (PreToolUse guards: secret-read block, wacli/send guard, identity lease).

## Config (`config.example.yaml`)
Top-level sections, each owned by the module named: `owner` (core: name, languages, tz, home {city, country, lat, lon}), `search` (db + discover: makes/models, budget, km/year limits, countries, excluded regions, wanted options, tiers, weights), `cardb` (db), `secrets` (core: backend), `notify` (core), `browsers`/`net`/`accounts` (browsers), `sites` (sites: enabled + overrides), `discover`, `contact` (channels, quiet hours, windows, caps, persona), `vet` (destination country, sources), `orchestrate` (backend, agent CLI, handover, schedule), `privacy` (denylist path). The example is the EV run, generalized.

## Clone → first sweep
1. Prereqs (README): macOS, Homebrew, [agterm](https://github.com/umputun/agterm), Claude Code, Docker. Bootstrap installs the rest.
2. `scripts/bootstrap`: brew deps (go, node@22, python@3.12, uv, gitleaks, jq, shfmt; wacli optional) → venv + `pip install -e .` → build `cardb` → `npm ci` in web → create `$CARHUNT_HOME` → copy `config.example.yaml` → `cardb init` → `docker compose up -d` → link skills into `~/.claude/skills/carhunt-*` (never overwrite a non-symlink) → register MCP servers (asks first) → agent Chrome setup → `scripts/install-hooks`. Idempotent; re-run is safe.
3. Edit `config.yaml`; `carhunt secret set …` for the optional providers (telegram, proxy, sms, gmail).
4. `carhunt doctor` → ok/warn/fail per component with the fix line.
5. `carhunt sweep --sites autoscout24 --dry-run`, then for real → cars in the web UI → `carhunt agent launch overseer`.

## Privacy model
- Generated locally, never committed: `$CARHUNT_HOME/**` (config, secrets, cardb data, photos, ledgers, rendered briefs, state, logs, profiles, cursors). `.gitignore` is a second line of defence.
- Committed: code, templates with `{placeholders}`, synthetic fixtures (VINs start `SYN`, phones `+<cc> 555…`, emails `@example.com`, URLs `example.invalid`).
- `scripts/privacy-check` runs as pre-commit + commit-msg hook (`scripts/install-hooks`): gitleaks + external denylist (`$CARHUNT_DENYLIST`, default `~/.config/carhunt/privacy-denylist.txt`; it reports line numbers, never terms) + regexes (phone, email, IBAN, VIN, key shapes, home paths). `--all` scans the tree, `--history` every commit. The integrator runs `--history` before push.

## Decisions (open to change)
| # | decision | why | alternative |
|---|---|---|---|
| D1 | macOS + agterm only in v1 | only proven setup; agterm required anyway | tmux backend + Linux secrets later |
| D2 | `evdb` renamed `cardb`; EV fields moved into `powertrain` | the repo is for any used car | keep `evdb` name |
| D3 | Ranking only in cardb | one answer for web, CLI, agents | discover-side scoring |
| D4 | Secrets: env → Keychain (default) / 1Password / file | no plaintext in repo or config | keyring lib |
| D5 | One Python package with auto-discovered CLI groups | no shared-file conflicts between builders | one script per tool |
| D6 | Telegram optional, policy (digest/ask/urgent only) enforced in code | EV run: half the pushes were noise | prose-only rule |
| D7 | Skills shipped as `carhunt-*` and symlinked | don't clash with the user's own skills | copy into `~/.claude/skills` |
