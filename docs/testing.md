# Testing

## Unit suites (offline)

| suite | command | needs |
|---|---|---|
| Python (all modules) | `.venv/bin/pytest -p no:cacheprovider` (repo root; ~3 min) | `.venv` from `scripts/bootstrap`; Playwright Chromium (`.venv/bin/python -m playwright install chromium`, bootstrap does it) or the page-driving tests (contact `test_sites`, access) skip; Go for the real-cardb tests (conftest builds it) |
| cardb (Go) | `cd cardb && go test ./...` (or `make -C cardb test`) | Go 1.26+ |
| web (vitest) | `cd web && npm ci && npm test` | Node >= 22.19 (`brew install node@22`: keg-only, put `$(brew --prefix node@22)/bin` on `PATH`) |
| web (Playwright) | `cd web && npm run e2e` | Go or `CARDB_BIN`; Chromium for Playwright (`npx playwright install chromium`) |
| privacy | `scripts/privacy-check --all` | `CARHUNT_DENYLIST`, gitleaks |

## End-to-end: `tests/e2e/run.sh`

A fresh clone run with an empty temp `HOME`, a scrubbed env and the real tools on `PATH`: bootstrap (twice) → cardb → sweep → web → doctor → `say --dry-run` → evidence → agent launch.

```sh
tests/e2e/run.sh                                  # main of this repo
E2E_REF=my-branch KEEP=1 tests/e2e/run.sh         # another ref; keep the work dir for inspection
E2E_KEEP_GOING=1 E2E_PATCH=/tmp/fix.diff tests/e2e/run.sh   # try an uncommitted fix, report every failing step
```

| knob | default | what |
|---|---|---|
| `E2E_SRC` | this repo's `.git` | clone source (path or URL) |
| `E2E_REF` | `main` | branch / tag / commit to check out |
| `E2E_PATCH` | none | comma list of diffs applied after the checkout (`git apply`) |
| `E2E_SKIP` | none | comma list of step ids to skip |
| `E2E_KEEP_GOING` | `0` | `1` = run every step after a failure (later steps may fail as a consequence) |
| `E2E_COMPOSE` | `0` | `1` = also build and run cardb with docker compose |
| `E2E_CACHES` | `warm` | share the Go/uv/npm/Playwright caches; `cold` = a first-time machine (slow) |
| `E2E_NODE_BIN` | first Node >= 22.19 found (brew `node@22`, nvm, `PATH`) | bin dir of a Node >= 22.19 |
| `E2E_TMP` | `/tmp` | base of the work dir; keep it short (agterm socket path < 104 bytes) |
| `KEEP` | `0` | `1` = keep the work dir (clone, `HOME`, logs in `logs/`) |

Step ids (for `E2E_SKIP`): `clone`, `home`, `bootstrap-dry`, `bootstrap`, `bootstrap2`, `cardb`, `compose`, `sweep`, `web-suite`, `web-live`, `doctor`, `say`, `evidence`, `agent`, `isolation`. `doctor` fails on any fail or any warn outside the allow-list in `run.sh` (optional providers).
