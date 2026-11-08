# deploy

`compose.yaml`: cardb (API, `127.0.0.1:8484`) + web (phone UI, `127.0.0.1:4321`) on this machine. Data lives in
`$CARHUNT_HOME/cardb` (bind mount), never in the repo or a named volume. Full guide: [`../docs/db.md`](../docs/db.md).

## Start

```sh
export CARHUNT_HOME=~/.carhunt                         # must be set: compose refuses to start without it
cardb init                                             # creates $CARHUNT_HOME/cardb/ + tokens file + secrets (once)
docker compose -f deploy/compose.yaml up -d --build cardb
curl -fsS http://127.0.0.1:8484/healthz                # {"ok":true,"version":"…"}  (same as /api/v1/health)

# web needs the per-user tokens as a compose secret, injected from the secrets backend (never written to disk here):
carhunt secret exec cardb_web_tokens=CARHUNT_SECRET_CARDB_WEB_TOKENS -- \
  docker compose -f deploy/compose.yaml up -d --build
```

Stop: `docker compose -f deploy/compose.yaml down` (data stays in `$CARHUNT_HOME/cardb`).
Version stamp: `CARDB_VERSION=$(git describe --tags --always) docker compose … up -d --build`.

## What the file guarantees

| item | value | why |
|---|---|---|
| ports | `127.0.0.1` only: cardb 8484, web 4321 (`PORT=4321`, `CARDB_URL=http://cardb:8484`) | the API is token-gated but not meant for the open internet; remote access = Tailscale or TLS proxy (docs/db.md) |
| cardb mounts | `$CARHUNT_HOME/cardb` → `/data`; `$CARHUNT_HOME/config.yaml` → `/config/config.yaml:ro` | one data dir = one backup path; profile is read-only to the server |
| missing mount source | start fails (long-syntax bind, no auto-create) | Docker would otherwise create an empty *directory* named `config.yaml` |
| tokens | `CARDB_TOKENS_FILE=/data/tokens` (written by `cardb init`, hashed) | no token in env or compose |
| web tokens | compose secret `cardb_web_tokens` (newline-separated `name:token`, owner + viewers, written by `cardb init`) ← env `CARHUNT_SECRET_CARDB_WEB_TOKENS` → `/run/secrets/cardb_web_tokens` (`CARDB_WEB_TOKENS_FILE`) | one cardb token per user, so every web write is that user's; the browser never sees a token (the web proxy adds it server-side) |
| hardening | `read_only`, tmpfs `/tmp`, `cap_drop: [ALL]`, `no-new-privileges`, non-root, `mem_limit` 768m/384m, `restart: unless-stopped`, healthchecks | a compromised container can't write outside `/data` or escalate |
| user | `${CARHUNT_UID:-10001}:${CARHUNT_GID:-10001}` | macOS Docker Desktop maps bind-mount ownership, so 10001 just works (verified). **Linux:** `sudo chown -R 10001:10001 $CARHUNT_HOME/cardb`, or run with `CARHUNT_UID=$(id -u) CARHUNT_GID=$(id -g)` |
| images | base images pinned by tag + sha256 (`cardb/Dockerfile`, `web/Dockerfile`) | compose builds from cached layers without pulling; a floating tag goes stale |
| `up cardb` alone | works while web isn't built | web depends on cardb (healthy), not the reverse |


## Check

```sh
docker compose -f deploy/compose.yaml config -q        # valid file (needs CARHUNT_HOME)
CARDB_SMOKE=1 go -C cardb test ./internal/cli -run TestLiveSmoke -count=1 -v   # read-only API smoke against localhost
```
