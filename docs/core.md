# core

Shared runtime for every module: config, secrets, owner-local clock, locks, run-data paths, notifier, cardb client, CLI dispatcher, doctor, bootstrap. Package `carhunt.core`. See also [notify.md](notify.md), [secrets.md](secrets.md).

## Commands

| command | what |
|---|---|
| `scripts/bootstrap [--dry-run] [--yes] [--skip-mcp] [--skip-browsers-launchd] [--skip-compose] [--extras all]` | clone → ready: brew deps, `.venv`, `carhunt` on PATH, cardb build + init, compose up, skills, browsers, hooks, doctor. Idempotent. |
| `scripts/doctor` = `carhunt doctor [--json]` | ok / warn / fail per component with a fix line; exit 1 on any fail |
| `carhunt config show [--json]` | the loaded config; secret refs shown as `secret:NAME`, never resolved |
| `carhunt config get KEY [--json]` | one value by dotted key (lists/maps as JSON; secret refs as `secret:NAME`); exit 1 if unset |
| `carhunt config validate [FILE]` | schema + time-zone check |
| `carhunt config path [--home]` | config file / `$CARHUNT_HOME` |
| `carhunt secret set\|ls\|check\|rm\|exec` | [secrets.md](secrets.md) |
| `carhunt notify send\|inbox list\|wait\|ack\|poll` | [notify.md](notify.md) |

## Python API (`carhunt.core`)

| module | API |
|---|---|
| `config` | `load(file=None) -> Config` (`$CARHUNT_CONFIG` or `$CARHUNT_HOME/config.yaml`; raises `ConfigError`), `load_or_none()`, `validate(dict) -> [errors]`, `home()`, `path(*parts)`. `Config.get("a.b.c", default)`, `.section(name)`, `.secret("a.b")` resolves a `secret:NAME`, `.as_dict()` (safe to print). |
| `secrets` | `get(name)`, `set(name, value)`, `exists(name)`, `delete(name)`, `names()`, `source(name)`; `SecretNotFound`, `SecretError` |
| `clock` | `tz()`, `now()`, `today()`, `in_window("HH:MM-HH:MM", at=None)`, `window_end(w)`, `next_start(w)`, `parse_window(w)` |
| `lock` | `with flock(name, timeout=None, shared=False):` → `$CARHUNT_HOME/locks/<name>.lock`; `LockTimeout` |
| `paths` | `home()`, `path(*p)`, `config_file()`, `agent_dir(role)`, `ledger_dir(module)` (= `$CARHUNT_HOME/<module>/`), `locks_dir()`, `secrets_dir()`, `pause_file()`, `paused()`, `safe_name()` |
| `notify` | `send(text, agent=, kind=, buttons=None, ask=False) -> ref\|None`, `deliver(...) -> Result(status sent\|held\|dropped, ref, until, silent)`, `inbox(agent).list/wait/ack/add`, `poll()`, `flush()`; `Refused`, `NotifyError` |
| `db` | `Client.from_config()`: `health, upsert_listing, find_listing, listing, listing_patch(version=), car, cars, car_patch, queue, status, fact, opt, verdict, event, events, msg, msgs, photo_add`, `request()` for the rest. Errors: `ApiError(status, body)` ⊃ `NotFound`, `Conflict` (409/412), `Unreachable`. |
| `doctor` | `Check(name, status ok\|warn\|fail, detail, fix)`, `run_all()`, `render()`, `exit_code()`; core's own `checks()` |

## Plugin contract (other modules)
- CLI: `carhunt/<pkg>/cli.py: register(subparsers)`; set `func=handler` (returns exit code). For a group, `p.set_defaults(_parser=p)` makes `carhunt <group>` alone print its help. A plugin that fails to import or register prints a warning; the rest of the CLI works.
- Doctor: `carhunt/<pkg>/doctor.py: checks() -> list[Check]`. A crash in it shows as one `fail` line, not a traceback. Modules from design.md that aren't installed show as `warn`. Core also checks cardb `/healthz` and the web UI `GET 127.0.0.1:4321/health` (`web.url` once the schema has it; down = warn: agents work without it).
- Bootstrap calls, when present: `make -C cardb build` (→ `cardb/bin/cardb`), `cardb init`, `deploy/compose.yaml`, `npm ci` in `web/`, `skills/carhunt-*` (symlinked), `browsers/install [--yes] [--skip-launchd] [--skip-mcp]`, `carhunt hooks install`, `scripts/install-hooks`.

## Env

| var | effect |
|---|---|
| `CARHUNT_HOME` | run-data root (default `~/.carhunt`) |
| `CARHUNT_CONFIG` | config file (default `$CARHUNT_HOME/config.yaml`) |
| `CARHUNT_TZ` | overrides `owner.tz` (tests) |
| `CARHUNT_FAKE_NOW` | pins `clock.now()`, ISO 8601; naive = owner-local |
| `CARHUNT_SECRET_<NAME>` | secret override (name upper-cased, non-alphanumerics → `_`) |
| `CARHUNT_SECRETS_BACKEND` | overrides `secrets.backend` |
| `CARHUNT_NOTIFY_BACKEND`, `CARHUNT_TELEGRAM_API` | override `notify.backend`, Telegram API base |
| `CARHUNT_AGENT` (or `CARDB_AUTHOR`) | default `--agent` for `notify` commands |
| `CARDB_URL`, `CARDB_AUTHOR` | cardb base URL; `X-Author` header |

## Config keys (core)

| key | default | note |
|---|---|---|
| `owner.tz` | required | IANA zone; every window (quiet hours, openers, schedule) is read in it. Bootstrap sets it from the Mac's zone. |
| `owner.name`, `owner.languages`, `owner.home` | | read by cardb / contact |
| `secrets.backend` | `keychain` (macOS) | `keychain \| op \| file`; `secrets.keychain_service` (default `carhunt`), `secrets.op_vault` (default `carhunt`) |
| `notify.*` | backend `none` | [notify.md](notify.md) |
| `cardb.url`, `cardb.token` | `http://127.0.0.1:8484`, `secret:cardb_token` | |

The schema is strict: an unknown key at any level fails validation (a typo like `notfy:` or `quiet_hour:` is an error, not a silent default). A module that adds a config key adds it to `carhunt/core/config.schema.json` and `config.example.yaml` in the same change.

## Rules (why)
- Run data only in `$CARHUNT_HOME`, never in the repo: the repo is shared; ledgers, chats and DB rows are private (docs/privacy.md).
- Config never holds a secret value, only `secret:NAME`; `Config` keeps refs unresolved so printing or logging it can't leak one.
- No hardcoded time zone: the EV run baked Lisbon into quiet hours, logs and wakes; a buyer elsewhere would get night pings.
- Windows are `[start, end)` and may cross midnight (`21:30-09:30`); `start == end` is an error, not "all day".
- Locks are `flock`: released when the holder dies, so a crashed agent can't wedge the others.

## Gaps
- `op` backend is unit-shaped only (no 1Password on the build machine).
- Linux: secrets `file` backend works; bootstrap is macOS-only (design D1).
