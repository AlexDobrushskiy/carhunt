# Testing

## Unit suites (offline, synthetic fixtures)

| suite | command | needs |
|---|---|---|
| Python (all modules) | `.venv/bin/pytest -p no:cacheprovider` (repo root; ~3 min) | `.venv` from `scripts/bootstrap`; Playwright Chromium (`.venv/bin/python -m playwright install chromium`, bootstrap does it) or the page-driving tests (contact `test_sites`, access) skip; Go for the real-cardb tests (conftest builds it) |
| cardb (Go) | `cd cardb && go test ./...` (or `make -C cardb test`) | Go 1.26+ |
| web (vitest) | `cd web && npm ci && npm test` | Node >= 22.19 (`brew install node@22`: keg-only, put `$(brew --prefix node@22)/bin` on `PATH`) |
| web (Playwright) | `cd web && npm run e2e` | Go or `CARDB_BIN`; Chromium for Playwright (`npx playwright install chromium`) |
| privacy | `scripts/privacy-check --all` | `CARHUNT_DENYLIST`, gitleaks |

## Isolation rules (every test)

- **Temp home.** Tests use a temp `CARHUNT_HOME` and never touch `~/.carhunt`, the real cardb or `~/.claude`.
- **File secrets.** Root `conftest.py` forces `CARHUNT_SECRETS_BACKEND=file` and blocks the real Keychain. Never weaken it: a module test once wrote to the real Keychain.
- **Offline.** No network in unit tests: sites parse hand-built fixtures, cardb runs in-process or on loopback.
- **Synthetic data only.** VINs `SYN…`, phones `+351 555 …`, hosts `example.invalid`; never a captured page, chat or DB row.
- **No sends.** Channels are stubbed; `carhunt say --dry-run` returns before any `send`.

## End-to-end: `tests/e2e/run.sh`

Proves that a stranger can clone the repo and run it: a fresh clone, an empty temp `HOME`, a scrubbed env (`env -i`), and the real tools on `PATH`. Run time is about 2.5 min with warm caches.

```sh
tests/e2e/run.sh                                  # main of this repo
E2E_REF=int/e2e KEEP=1 tests/e2e/run.sh           # another ref; keep the work dir for inspection
E2E_KEEP_GOING=1 E2E_PATCH=/tmp/fix.diff tests/e2e/run.sh   # try an uncommitted fix, report every failing step
```

| knob | default | what |
|---|---|---|
| `E2E_SRC` | this repo's `.git` | clone source (path or URL) |
| `E2E_REF` | `main` | branch / tag / commit to check out |
| `E2E_PATCH` | none | comma list of diffs applied after the checkout (`git apply`) |
| `E2E_SKIP` | none | comma list of step ids to skip |
| `E2E_KEEP_GOING` | `0` | `1` = run every step after a failure (later steps may fail as a consequence) |
| `E2E_COMPOSE` | `0` | `1` = also build and run cardb with docker compose (own project, port and image names; removed after) |
| `E2E_CACHES` | `warm` | share the Go/uv/npm/Playwright caches (a missing Chromium revision is downloaded into the real `~/Library/Caches/ms-playwright` once); `cold` = a true first-time machine (slow) |
| `E2E_NODE_BIN` | first Node >= 22.19 among: `$(brew --prefix node@22)/bin`, nvm installs (newest first), `node` on `PATH` | bin dir of a Node >= 22.19 (web deps: undici 8); candidates are checked by version, not name |
| `E2E_TMP` | `/tmp` | base of the work dir: keep it short, since the agterm socket path must stay under 104 bytes |
| `KEEP` | `0` | `1` = keep the work dir (clone, `HOME`, logs in `logs/`) |

### Steps (ids for `E2E_SKIP`)

| id | does | proves |
|---|---|---|
| `clone` | `git clone` + checkout (+ patches) | the committed tree is complete: nothing depends on the dev's untracked files |
| `home` | temp `HOME`, scrubbed env, guard stubs for `security` and `launchctl` writes | no `CLAUDE_CONFIG_DIR` / `CARHUNT_*` / tokens leak in |
| `bootstrap-dry` | `scripts/bootstrap --dry-run …` | the dry run only prints its plan: `HOME` stays unchanged |
| `bootstrap` | `scripts/bootstrap --yes --skip-mcp --skip-browsers-launchd --skip-compose --skip-schedule` | venv, `carhunt`/`cardb` on `PATH`, Playwright Chromium, cardb build + init (file secrets), config, folder trust, guard hooks + statusline in `$CARHUNT_HOME/claude/settings.json` (and none in `~/.claude`), browsers/install (Agent Chrome clone) |
| `bootstrap2` | the same command again | re-runs are safe: the config, the cardb tokens and the agent `settings.json` stay the same |
| `cardb` | `cardb serve` on a free port, `cardb.url` rewritten in the config (in place, validated) | the host binary serves; the port is configurable |
| `compose` | (`E2E_COMPOSE=1`) `docker compose up --build cardb` on another free port | the image builds and passes its health check |
| `sweep` | `carhunt sweep --sites fake --max 5` then `cardb ls` | discover → sites (fixture plugin) → cardb writes: ≥ 1 car |
| `web-suite` | `npm run e2e` in `web/` with `CARDB_BIN` = the built cardb | the web's own Playwright suite (throwaway cardb + synthetic seed) |
| `web-live` | build the web and start it on the swept cardb, with tokens from `carhunt secret exec` | `/health` responds, a page shows the swept car; `web.url` in the config is set to it (doctor checks this instance) |
| `doctor` | `carhunt doctor --json` with cardb and web up | no `fail`; only the allowed warns (below) |
| `say` | `carhunt say --channel whatsapp --car N --opener --dry-run`, with a stub `wacli` that logs its calls | guard decision + payload (exit 0 or 10); the stub logs no `send` |
| `evidence` | `carhunt evidence N` and `--write-asks` | vet reads cardb (exit 0 = visit-ready, 4 = items missing) and writes an `ask` event |
| `agent` | `carhunt agent launch e2e-dummy` (a user-local role, a stub `claude` that writes a marker), then `carhunt agent close` | a real agterm session starts with `CARHUNT_AGENT`/`CARHUNT_HOME`/`CARDB_AUTHOR` and closes; none is left open |
| `isolation` | always runs | no blocked Keychain or launchd write was attempted; the real `carhunt.*` launchd labels and Claude Code `settings.json` (`~/.claude` and `$CLAUDE_CONFIG_DIR`) are unchanged |

### Expected doctor warns (allow-list in `run.sh`)

| check prefix | why it may warn on a fresh machine |
|---|---|
| `notify` | Telegram is optional |
| `access: proxy`, `access: sms` | the residential proxy and the SMS provider are optional |
| `access: captcha.` | the local captcha solver is off by default |
| `contact.secret.gmail_`, `contact.wacli` | the Gmail and WhatsApp channels are optional |
| `access: mcp servers` | the browser MCP servers run under launchd, which the e2e skips |
| `access: identity master` | the owner's one-time site logins (`pw-identity login`) are manual |
| `orchestrate.schedule` | the launchd day schedule is skipped in the e2e |

Any other warn, or any fail, fails the step.

### Design choices

- **cardb runs with `cardb serve`, not compose.** It needs no Docker daemon and no image build (~1 s against ~20 s), and it gets a free port, so it never clashes with a stack already on 8484/4321. Compose is still covered by `E2E_COMPOSE=1`, with its own project, port and image names, which are removed afterwards.
- **The env is scrubbed (`env -i` plus an allow-list).** This dev machine sets `CLAUDE_CONFIG_DIR`, `AGTERM_SESSION_ID` and similar variables, and a stranger doesn't have them.
- **Guard stubs come first on `PATH`.** The `security` stub, and the `launchctl` stub for writes, log the call and fail, so a regression that reaches the real Keychain or launchd fails the run instead of silently succeeding.
- **agterm is real.** The real agterm socket is linked into the temp `HOME` (`agtermctl` reads it only from `$HOME/Library/Application Support/agterm/`). The agent CLI is a stub, so no Claude session starts.
- **Cleanup.** An `EXIT` trap closes the agterm session, stops cardb and the web, brings down the compose project and deletes the work dir (unless `KEEP=1`), on failure too.
