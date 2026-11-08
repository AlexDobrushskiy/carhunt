#!/usr/bin/env bash
# carhunt end-to-end on a clean checkout and a temp HOME: "a stranger can clone and run it".
# clone → bootstrap (twice) → cardb serve → doctor → sweep (fake site) → web → say --dry-run → evidence → agent launch.
# Knobs, what each step proves, expected warns: docs/testing.md.
set -euo pipefail

SELF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SELF=$SELF_DIR/$(basename "${BASH_SOURCE[0]}")

# ---------------------------------------------------------------------------------------------------------------------
# Outer: build the work dir and re-exec in a scrubbed env (env -i). Nothing from the caller's shell leaks in except the
# allow-list below: no CLAUDE_CONFIG_DIR, CARHUNT_*, CARDB_*, AGTERM_SESSION_ID, tokens.
if [ -z "${_E2E_INNER:-}" ]; then
  REAL_HOME=$HOME
  # Short base: the agterm socket link lives at $HOME/Library/Application Support/agterm/agterm.sock and a unix
  # socket path must stay under 104 bytes (the macOS $TMPDIR is too long for it).
  W=$(mktemp -d "${E2E_TMP:-/tmp}/carhunt-e2e.XXXXXX")
  W=$(cd "$W" && pwd -P)
  mkdir -p "$W/home" "$W/stubs" "$W/logs" "$W/state"

  node_ok() {  # node_ok BINDIR: its node is >= 22.19 (web deps: undici 8)
    local v; v=$("$1/node" -v 2>/dev/null | sed 's/^v//')
    [ -n "$v" ] && [ "$(printf '%s\n' 22.19.0 "$v" | sort -V | head -1)" = 22.19.0 ]
  }
  # Node: E2E_NODE_BIN, else Homebrew's keg-only node@22, else the newest nvm Node, else node on PATH (each >= 22.19)
  NODE_BIN=
  cands=("${E2E_NODE_BIN:-}")
  keg="$(command -v brew >/dev/null && brew --prefix node@22 2>/dev/null || true)/bin"
  "$keg/node" -v 2>/dev/null | grep -q '^v22\.' && cands+=("$keg")   # only a real Node 22 (opt link can be stale)
  for d in $(ls -d "$REAL_HOME"/.nvm/versions/node/v*/bin 2>/dev/null | sort -rV); do cands+=("$d"); done
  command -v node >/dev/null && cands+=("$(dirname "$(command -v node)")")
  for d in "${cands[@]}"; do [ -n "$d" ] && node_ok "$d" && { NODE_BIN=$d; break; }; done
  [ -n "$NODE_BIN" ] || { echo "e2e: needs Node >= 22.19 (brew install node@22, or set E2E_NODE_BIN)" >&2; exit 2; }
  [ -n "${E2E_NODE_BIN:-}" ] && [ "$NODE_BIN" != "$E2E_NODE_BIN" ] && { echo "e2e: E2E_NODE_BIN node is older than 22.19" >&2; exit 2; }

  # Guard stubs, first on PATH: the real Keychain and launchd writes are refused and logged (step "isolation" fails on any).
  cat >"$W/stubs/security" <<'SH'
#!/bin/sh
echo "security $*" >>"$_E2E_WORK/logs/blocked.log"
echo "e2e: real Keychain blocked (security $1)" >&2
exit 44
SH
  REAL_LAUNCHCTL=$(command -v launchctl || echo /bin/launchctl)
  cat >"$W/stubs/launchctl" <<SH
#!/bin/sh
case "\$1" in list|print|print-disabled|blame|version|help) exec "$REAL_LAUNCHCTL" "\$@" ;; esac
echo "launchctl \$*" >>"\$_E2E_WORK/logs/blocked.log"
echo "e2e: launchd write blocked (launchctl \$1)" >&2
exit 44
SH
  chmod +x "$W/stubs/security" "$W/stubs/launchctl"

  envs=(
    "HOME=$W/home" "USER=${USER:-$(id -un)}" "LOGNAME=${LOGNAME:-$(id -un)}" "SHELL=${SHELL:-/bin/zsh}"
    "TERM=${TERM:-dumb}" "LANG=${LANG:-en_US.UTF-8}" "TMPDIR=${TMPDIR:-/tmp}"
    "PATH=$W/stubs:$W/home/.local/bin:$NODE_BIN:$PATH"
    "_E2E_REAL_CLAUDE_DIR=${CLAUDE_CONFIG_DIR:-$REAL_HOME/.claude}"
    "_E2E_INNER=1" "_E2E_WORK=$W" "_E2E_SELF=$SELF" "_E2E_REAL_HOME=$REAL_HOME" "_E2E_REAL_LAUNCHCTL=$REAL_LAUNCHCTL"
    "CARHUNT_SECRETS_BACKEND=file" "CARHUNT_FAKE_SITES=1"
  )
  for k in E2E_SRC E2E_REF E2E_PATCH E2E_TMP KEEP E2E_KEEP_GOING E2E_SKIP E2E_COMPOSE E2E_CACHES E2E_VERBOSE; do
    [ -n "${!k:-}" ] && envs+=("$k=${!k}")
  done
  # agtermctl looks for agterm's control socket under $HOME only (AGTERM_SOCKET is ignored): link the real one in.
  sock=${AGTERM_SOCKET:-$REAL_HOME/Library/Application Support/agterm/agterm.sock}
  if [ -S "$sock" ]; then
    mkdir -p "$W/home/Library/Application Support/agterm"
    ln -s "$sock" "$W/home/Library/Application Support/agterm/agterm.sock"
    envs+=("AGTERM_SOCKET=$sock")
  fi
  # Warm caches by default (content-addressed, safe to share); E2E_CACHES=cold = a true first-time machine.
  if [ "${E2E_CACHES:-warm}" != cold ]; then
    command -v go >/dev/null && envs+=("GOMODCACHE=$(go env GOMODCACHE)" "GOCACHE=$(go env GOCACHE)")
    command -v uv >/dev/null && envs+=("UV_CACHE_DIR=$(uv cache dir)")
    envs+=("npm_config_cache=$REAL_HOME/.npm")
    [ -d "$REAL_HOME/Library/Caches/ms-playwright" ] && envs+=("PLAYWRIGHT_BROWSERS_PATH=$REAL_HOME/Library/Caches/ms-playwright")
  fi
  # Docker Desktop's CLI context lives in the real ~/.docker; only the optional compose step needs it.
  [ "${E2E_COMPOSE:-0}" = 1 ] && envs+=("DOCKER_CONFIG=$REAL_HOME/.docker")

  exec env -i "${envs[@]}" bash "$SELF" "$@"
fi

# ---------------------------------------------------------------------------------------------------------------------
# Inner: every step runs in a subshell with set -e; state crosses steps through $W/state/env.
W=$_E2E_WORK
REAL_HOME=$_E2E_REAL_HOME
LOGS=$W/logs
STATE=$W/state/env
CLONE=$W/carhunt
export CARHUNT_HOME=$HOME/.carhunt          # bootstrap's default: what a stranger gets
CH=$CARHUNT_HOME
touch "$STATE" "$LOGS/blocked.log"

banner() { printf '\n\033[1m==== [%s] %s\033[0m\n' "$1" "$2"; }
info() { printf '  %s\n' "$*"; }
die() { printf '  FAIL: %s\n' "$*" >&2; exit 1; }
setstate() { printf '%s=%q\n' "$1" "$2" >>"$STATE"; }
load() { . "$STATE"; }
venv() { "$CLONE/.venv/bin/$@"; }
free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'; }
wait_http() {  # wait_http URL PIDFILE WHAT [SECONDS]
  local i=0 max=$((${4:-30} * 5))
  while [ $i -lt $max ]; do
    curl -fsS -o /dev/null "$1" 2>/dev/null && return 0
    [ -n "$2" ] && ! kill -0 "$(cat "$2")" 2>/dev/null && die "$3 exited before $1 answered (log: $LOGS)"
    sleep 0.2; i=$((i + 1))
  done
  die "$3 not up at $1 after ${4:-30}s"
}
# set_url SECTION URL: rewrite SECTION.url in the config in place (keeps comments), then check it parses + validates
set_url() {
  venv python - "$CH/config.yaml" "$1" "$2" <<'PY' || die "could not set $1.url in config.yaml"
import re, sys, yaml
path, section, url = sys.argv[1:]
lines, out, inside, done = open(path).read().splitlines(keepends=True), [], False, False
for ln in lines:
    if re.match(r"^\S", ln):
        inside = ln.startswith(section + ":")
    m = re.match(r"^(  url:\s*)(\S+)(.*)$", ln, re.S) if inside and not done else None
    if m:
        ln, done = f"{m.group(1)}{url}{m.group(3)}", True
    out.append(ln)
if not done:
    sys.exit(f"no {section}.url key")
open(path, "w").write("".join(out))
assert (yaml.safe_load(open(path)) or {})[section]["url"] == url
PY
  carhunt config validate >/dev/null || die "config invalid after setting $1.url"
}
# cars_field FIELD: FIELD of the first car in $LOGS/cars.json (`cardb ls --json`: {"cars": [...]}, or a list)
cars_field() {
  venv python -c 'import json,sys; d=json.load(open(sys.argv[1])); d=d if isinstance(d,list) else d.get("cars") or d.get("items") or []; print(len(d) if sys.argv[2]=="count" else (d[0].get(sys.argv[2]) or "") if d else "")' "$LOGS/cars.json" "$1"
}
cksum_of() { [ -e "$1" ] && shasum -a 256 "$1" | cut -d' ' -f1 || echo absent; }

# ---- cleanup: stop everything we started, then remove the work dir (KEEP=1 keeps it) ----
cleanup() {
  local rc=$?
  set +e
  load 2>/dev/null
  if [ -n "${AGENT_SID:-}" ] && agtermctl tree --json 2>/dev/null | grep -qi "$AGENT_SID"; then
    agtermctl session close --target "$AGENT_SID" >/dev/null 2>&1 && info "closed agterm session $AGENT_SID"
  fi
  for f in "$W"/state/*.pid; do
    [ -f "$f" ] || continue
    pid=$(cat "$f")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
      kill -9 "$pid" 2>/dev/null
      info "stopped $(basename "$f" .pid) (pid $pid)"
    fi
  done
  if [ -n "${COMPOSE_PROJECT:-}" ]; then
    CARHUNT_CARDB_IMAGE=$COMPOSE_PROJECT/cardb:e2e CARHUNT_WEB_IMAGE=$COMPOSE_PROJECT/web:e2e docker compose -p "$COMPOSE_PROJECT" -f "$CLONE/deploy/compose.yaml" \
      down -v --rmi all >/dev/null 2>&1
    info "compose project $COMPOSE_PROJECT down"
  fi
  print_summary
  if [ "${KEEP:-0}" = 1 ]; then info "KEEP=1: work dir kept at $W (HOME=$HOME)"
  else
    case "$W" in  # only ever the mktemp dir made by the outer half: non-empty, named carhunt-e2e.XXXXXX
      /?*/carhunt-e2e.??????) chmod -R u+w "$W" 2>/dev/null; rm -rf -- "$W" ;;
      *) info "refusing to delete unexpected work dir '$W'" ;;
    esac
  fi
  exit $rc
}
trap cleanup EXIT
trap 'exit 130' INT TERM

RESULTS=()
print_summary() {
  [ ${#RESULTS[@]} -gt 0 ] || return 0
  printf '\n\033[1m==== summary\033[0m\n'
  printf '  %s\n' "${RESULTS[@]}"
}

FAILED=0
# run_step ID TITLE FN [always]: subshell + set -e; a failure stops the run unless E2E_KEEP_GOING=1 ("always" steps
# still run).
run_step() {
  local id=$1 title=$2 fn=$3 always=${4:-} rc t0=$SECONDS
  case ",${E2E_SKIP:-}," in *",$id,"*) RESULTS+=("SKIP  $id  (E2E_SKIP)"); return 0 ;; esac
  if [ "$FAILED" = 1 ] && [ "${E2E_KEEP_GOING:-0}" != 1 ] && [ -z "$always" ]; then
    RESULTS+=("----  $id  (not run)"); return 0
  fi
  banner "$id" "$title"
  set +e
  (set -euo pipefail; load; "$fn")
  rc=$?
  set -e
  if [ $rc -eq 0 ]; then RESULTS+=("PASS  $id  ($((SECONDS - t0))s)")
  else RESULTS+=("FAIL  $id  (exit $rc, $((SECONDS - t0))s)"); FAILED=1; fi
}

# ---------------------------------------------------------------------------------------------------------------------
step_clone() {
  local src=${E2E_SRC:-} ref=${E2E_REF:-main}
  if [ -z "$src" ]; then  # default: the repo this script lives in (its common .git, so a worktree works too)
    src=$(git -C "$(dirname "$_E2E_SELF")" rev-parse --path-format=absolute --git-common-dir)
  fi
  info "source $src @ $ref"
  git clone -q "$src" "$CLONE"
  git -C "$CLONE" checkout -q "$ref"
  info "HEAD $(git -C "$CLONE" log -1 --format='%h %s')"
  if [ -n "${E2E_PATCH:-}" ]; then  # try uncommitted fixes: comma list of diff files, applied in order
    local p; IFS=, read -ra patches <<<"$E2E_PATCH"
    for p in "${patches[@]}"; do git -C "$CLONE" apply --index "$p" || die "E2E_PATCH $p does not apply"; info "applied $p"; done
  fi
}

step_home() {
  [ "$HOME" != "$REAL_HOME" ] || die "HOME is the real home"
  [ -z "${CLAUDE_CONFIG_DIR:-}" ] || die "CLAUDE_CONFIG_DIR leaked into the e2e env"
  case "$CH" in "$W"/*) ;; *) die "CARHUNT_HOME $CH is outside the work dir" ;; esac
  [ "$(command -v security)" = "$W/stubs/security" ] || die "security stub not first on PATH"
  [ "$(printf '%s\n' 22.19.0 "$(node -v | sed 's/^v//')" | sort -V | head -1)" = 22.19.0 ] || die "node $(node -v) on PATH; need >= 22.19"
  # Baselines for the isolation step: real launchd labels and the real Claude settings.
  "$_E2E_REAL_LAUNCHCTL" list | awk '{print $3}' | grep '^carhunt\.' | sort >"$W/state/launchd.before" || true
  setstate REAL_SETTINGS_SUM "$(cksum_of "$REAL_HOME/.claude/settings.json")$(cksum_of "$_E2E_REAL_CLAUDE_DIR/settings.json")"
  info "HOME=$HOME  CARHUNT_HOME=$CH  node $(node -v)  go $(go env GOVERSION 2>/dev/null || echo -)"
}


home_tree() {  # HOME minus tool caches/telemetry (brew refreshes its API cache on `brew list`, go writes telemetry)
  (cd "$HOME" && find . \( -path ./Library/Caches -o -path "./Library/Application Support/go" -o -path ./.cache \
    -o -path ./.npm \) -prune -o -print | sort)
}
BOOT_FLAGS=(--yes --skip-mcp --skip-browsers-launchd --skip-compose --skip-schedule)

step_bootstrap_dry() {  # --dry-run must print the plan and change nothing
  home_tree >"$W/state/home.before"
  "$CLONE/scripts/bootstrap" --dry-run "${BOOT_FLAGS[@]}" >"$LOGS/bootstrap-dry.log" 2>&1 \
    || { tail -30 "$LOGS/bootstrap-dry.log"; die "bootstrap --dry-run failed"; }
  home_tree | diff "$W/state/home.before" - | head -20 || true
  home_tree | cmp -s "$W/state/home.before" - || die "bootstrap --dry-run changed files under HOME (diff above)"
  [ ! -e "$CLONE/.venv" ] || die "bootstrap --dry-run created .venv"
  info "$(grep -c 'would ' "$LOGS/bootstrap-dry.log") planned actions, nothing changed"
}

step_bootstrap() {
  "$CLONE/scripts/bootstrap" "${BOOT_FLAGS[@]}" 2>&1 | tee "$LOGS/bootstrap.log"
  local f
  for f in "$CLONE/.venv/bin/carhunt" "$CLONE/cardb/bin/cardb" "$CH/config.yaml" "$CH/cardb/tokens" \
    "$HOME/.local/bin/carhunt" "$HOME/.local/bin/cardb" "$HOME/.claude.json" "$CH/claude/settings.json" \
    "$CH/secrets/cardb_token"; do
    [ -e "$f" ] || die "bootstrap did not create $f"
  done
  [ "$(stat -f %Lp "$CH")" = 700 ] || die "$CH is not mode 700"
  venv python - "$HOME/.claude.json" "$CH" <<'PY' || die "folder trust for CARHUNT_HOME not set"
import json, os, sys
p = json.load(open(sys.argv[1])).get("projects", {})
sys.exit(0 if p.get(os.path.realpath(sys.argv[2]), {}).get("hasTrustDialogAccepted") is True else 1)
PY
  # guard hooks + statusline live in the agent settings (claude --settings); the user's own settings stay untouched
  grep -q carhunt "$CH/claude/settings.json" || die "no carhunt hooks in \$CARHUNT_HOME/claude/settings.json"
  grep -q '"statusLine"' "$CH/claude/settings.json" || die "statusLine not set in the agent settings"
  [ ! -e "$HOME/.claude/settings.json" ] || die "bootstrap wrote ~/.claude/settings.json"
  venv python -c 'from playwright.sync_api import sync_playwright as p
import os, sys
with p() as pw: sys.exit(0 if os.path.exists(pw.chromium.executable_path) else 1)' || die "Playwright Chromium not installed"
  setstate CONFIG_SUM "$(cksum_of "$CH/config.yaml")"
  setstate TOKENS_SUM "$(cksum_of "$CH/cardb/tokens")"
  setstate SETTINGS_SUM "$(cksum_of "$CH/claude/settings.json")"
}

step_bootstrap_again() {
  "$CLONE/scripts/bootstrap" "${BOOT_FLAGS[@]}" >"$LOGS/bootstrap2.log" 2>&1 || { tail -30 "$LOGS/bootstrap2.log"; die "second bootstrap failed"; }
  tail -3 "$LOGS/bootstrap2.log"
  [ "$(cksum_of "$CH/config.yaml")" = "$CONFIG_SUM" ] || die "re-run changed config.yaml"
  [ "$(cksum_of "$CH/cardb/tokens")" = "$TOKENS_SUM" ] || die "re-run rotated the cardb tokens"
  [ "$(cksum_of "$CH/claude/settings.json")" = "$SETTINGS_SUM" ] || die "re-run changed the agent settings.json"
}

step_cardb() {
  local port; port=$(free_port)
  "$CLONE/cardb/bin/cardb" version >/dev/null 2>&1 || true
  CARDB_LISTEN=127.0.0.1:$port nohup "$CLONE/cardb/bin/cardb" serve >"$LOGS/cardb.log" 2>&1 &
  echo $! >"$W/state/cardb.pid"
  wait_http "http://127.0.0.1:$port/healthz" "$W/state/cardb.pid" "cardb serve"
  # Point the config at this port, as a user with a busy 8484 would.
  set_url cardb "http://127.0.0.1:$port"
  setstate CARDB_URL "http://127.0.0.1:$port"
  info "cardb serve on 127.0.0.1:$port ($(curl -fsS "http://127.0.0.1:$port/healthz"))"
}

step_compose() {  # optional (E2E_COMPOSE=1): the Docker path builds and serves on an alternate port
  [ "${E2E_COMPOSE:-0}" = 1 ] || { info "skipped (set E2E_COMPOSE=1)"; return 0; }
  local port project; port=$(free_port); project=carhunt-e2e-$(basename "$W" | tr 'A-Z.' 'a-z-')
  setstate COMPOSE_PROJECT "$project"
  CARHUNT_CARDB_PORT=$port CARHUNT_CARDB_IMAGE=$project/cardb:e2e CARHUNT_WEB_IMAGE=$project/web:e2e docker compose -p "$project" -f "$CLONE/deploy/compose.yaml" up -d --build cardb \
    >"$LOGS/compose.log" 2>&1 || { tail -30 "$LOGS/compose.log"; die "compose up failed"; }
  wait_http "http://127.0.0.1:$port/healthz" "" "compose cardb" 90
  info "compose cardb healthy on 127.0.0.1:$port"
}

# Doctor warns expected on a fresh machine with only the required pieces (check-name prefix  # why it may warn):
DOCTOR_ALLOWED_WARN=(
  'notify'                  # optional Telegram notifier, unset
  'access: proxy'           # optional residential proxy, unset
  'access: sms'             # optional one-time SMS provider, unset
  'access: captcha.'        # optional local captcha solver: off by default
  'contact.secret.gmail_'   # optional Gmail channel: no OAuth secrets
  'contact.wacli'           # optional WhatsApp CLI: not installed / not linked
  'access: mcp servers'     # browser MCP servers run under launchd: skipped here (--skip-browsers-launchd)
  'access: identity master' # needs the owner's one-time site logins (pw-identity login): manual by design
  'orchestrate.schedule'    # launchd day schedule: skipped here (--skip-schedule)
)
step_doctor() {
  local rc=0
  carhunt doctor >"$LOGS/doctor.txt" 2>&1 || rc=$?
  carhunt doctor --json >"$LOGS/doctor.json" 2>/dev/null || true
  cat "$LOGS/doctor.txt"
  venv python - "$LOGS/doctor.json" "${DOCTOR_ALLOWED_WARN[@]}" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
allowed = tuple(sys.argv[2:])
bad = [r for r in rows if r.get("status") == "fail"]
odd = [r for r in rows if r.get("status") == "warn" and not str(r.get("name", "")).startswith(allowed)]
for r in bad: print(f"  doctor FAIL: {r.get('name')}: {r.get('detail', '')}")
for r in odd: print(f"  doctor unexpected warn: {r.get('name')}: {r.get('detail', '')}")
print(f"  {len(rows)} checks, {len(bad)} fail, {len(odd)} unexpected warn")
sys.exit(1 if bad or odd or not rows else 0)
PY
  [ $rc -eq 0 ] || die "carhunt doctor exited $rc"
}

step_sweep() {
  export CARDB_URL
  carhunt sweep --sites fake --max 5 --json >"$LOGS/sweep.json" 2>"$LOGS/sweep.err" || { cat "$LOGS/sweep.err"; die "sweep failed"; }
  head -c 2000 "$LOGS/sweep.json"; echo
  cardb ls --json >"$LOGS/cars.json" || die "cardb ls failed"
  local n; n=$(cars_field count)
  [ "$n" -ge 1 ] || die "no cars in cardb after the sweep"
  local car; car=$(cars_field id)
  setstate CAR_ID "$car"
  info "$n car(s) in cardb; first car id $car"
}

step_web_suite() {  # web's own Playwright suite: throwaway cardb (our built binary) + this web, synthetic seed
  cd "$CLONE/web"
  [ -d node_modules ] || npm ci --no-audit --no-fund --loglevel=error
  npx playwright --version >/dev/null
  if [ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ]; then
    export PLAYWRIGHT_BROWSERS_PATH=$W/ms-playwright
    npx playwright install chromium >"$LOGS/playwright-install.log" 2>&1 || die "playwright install chromium failed"
  fi
  CARDB_BIN=$CLONE/cardb/bin/cardb E2E_OUT=$W/web-results npm run e2e 2>&1 | tee "$LOGS/web-e2e.log" | tail -40
}

step_web_live() {  # this web on the swept cardb: /health + the list page shows a swept car
  cd "$CLONE/web"
  [ -d node_modules ] || npm ci --no-audit --no-fund --loglevel=error
  npm run build >"$LOGS/web-build.log" 2>&1 || { tail -30 "$LOGS/web-build.log"; die "web build failed"; }
  local port; port=$(free_port)
  HOST=127.0.0.1 PORT=$port NODE_ENV=production CARDB_URL=$CARDB_URL nohup \
    carhunt secret exec cardb_web_tokens=CARDB_WEB_TOKENS -- node ./dist/server/entry.mjs >"$LOGS/web.log" 2>&1 &
  echo $! >"$W/state/web.pid"
  wait_http "http://127.0.0.1:$port/health" "$W/state/web.pid" "web"
  info "/health: $(curl -fsS "http://127.0.0.1:$port/health" | head -c 200)"
  local model; model=$(cars_field model)
  [ -n "$model" ] || die "no swept car to look for"
  local page found=""
  for page in / /queue "/cars/$CAR_ID"; do
    curl -fsS "http://127.0.0.1:$port$page" >"$LOGS/web-page.html" || die "GET $page failed"
    if grep -qF "$model" "$LOGS/web-page.html"; then found=$page; break; fi
  done
  [ -n "$found" ] || die "no web page shows the swept model '$model' (tried /, /queue, /cars/$CAR_ID)"
  info "swept car '$model' visible on $found"
  set_url web "http://127.0.0.1:$port"   # doctor's web check targets this instance
  info "config web.url = http://127.0.0.1:$port"
}

step_say() {  # dry run decides and shows the payload; wacli is a logging stub that would record any send
  local stub=$W/stubs-say; mkdir -p "$stub"
  cat >"$stub/wacli" <<'SH'
#!/bin/sh
echo "wacli $*" >>"$_E2E_WORK/logs/wacli.calls"
case " $* " in *" send "*) echo "e2e: wacli send reached" >&2; exit 45 ;; esac
echo '{"success":true,"data":{"messages":[]}}'
SH
  chmod +x "$stub/wacli"
  local rc=0
  CARHUNT_WACLI=$stub/wacli CARDB_URL=$CARDB_URL carhunt say --channel whatsapp --car "$CAR_ID" --opener \
    --text "Hello, is the car still available?" --dry-run --json >"$LOGS/say.json" 2>"$LOGS/say.err" || rc=$?
  cat "$LOGS/say.json" "$LOGS/say.err"
  # 0 = guard would send, 10 = guard refused (e.g. quiet hours by the clock): both are valid dry-run decisions.
  case $rc in 0|10) ;; *) die "say --dry-run exited $rc" ;; esac
  [ -s "$LOGS/say.json" ] || die "say --dry-run printed no decision"
  if grep -q ' send ' "$LOGS/wacli.calls" 2>/dev/null; then die "dry run invoked wacli send"; fi
  info "decision exit $rc; wacli calls: $(wc -l <"$LOGS/wacli.calls" 2>/dev/null | tr -d ' ' || echo 0), none of them send"
}

step_evidence() {  # exit 0 = visit-ready, 4 = items missing (a fresh swept car): both are a working evidence check
  local rc=0 rc2=0
  CARDB_URL=$CARDB_URL carhunt evidence "$CAR_ID" --json >"$LOGS/evidence.json" 2>"$LOGS/evidence.err" || rc=$?
  case $rc in 0|4) ;; *) cat "$LOGS/evidence.err"; die "evidence exited $rc" ;; esac
  CARDB_URL=$CARDB_URL carhunt evidence "$CAR_ID" --write-asks --json >"$LOGS/evidence-asks.json" 2>"$LOGS/evidence.err" || rc2=$?
  case $rc2 in 0|4) ;; *) cat "$LOGS/evidence.err"; die "evidence --write-asks exited $rc2" ;; esac
  venv python - "$LOGS/evidence.json" <<'PY' || die "evidence JSON lacks items"
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("items"), d
print(f"  {sum(i['state'] == 'have' for i in d['items'])}/{len(d['items'])} evidence items present, visit_ready={d.get('visit_ready')}")
PY
  # items are missing on a fresh car, so --write-asks must leave an `ask` event for the outreach agent
  CARDB_URL=$CARDB_URL cardb events "$CAR_ID" --json >"$LOGS/events.json" || die "cardb events failed"
  grep -Eq '"type": *"ask"' "$LOGS/events.json" || die "no ask event in cardb after evidence --write-asks"
  info "ask event written to cardb"
}

step_agent() {  # launch a dummy role in a real agterm session with a stub agent CLI, check it ran, close it
  command -v agtermctl >/dev/null || die "agtermctl not on PATH (agterm is required)"
  agtermctl tree --json >/dev/null 2>&1 || die "agterm not reachable (AGTERM_SOCKET=${AGTERM_SOCKET:-unset})"
  local bin=$W/agentbin role=e2e-dummy
  mkdir -p "$bin" "$CH/roles/$role"
  ln -sf "$CLONE/.venv/bin/carhunt" "$bin/carhunt"   # launch puts dirname(which carhunt) first on the agent's PATH
  cat >"$bin/claude" <<'SH'
#!/bin/sh
# Stub agent CLI for the e2e: proves the session started with the agent env, then idles until closed.
printf 'role=%s home=%s author=%s\n' "$CARHUNT_AGENT" "$CARHUNT_HOME" "$CARDB_AUTHOR" >"$CARHUNT_HOME/e2e-agent-ran"
echo "carhunt e2e dummy agent ($CARHUNT_AGENT): idle, will exit in 300s"
sleep 300
SH
  chmod +x "$bin/claude"
  printf '# e2e dummy role\n\nDo nothing. This role exists only for tests/e2e/run.sh.\n' >"$CH/roles/$role/brief.md"
  PATH=$bin:$PATH carhunt agent launch "$role" >"$LOGS/agent-launch.json" 2>"$LOGS/agent-launch.err" \
    || { cat "$LOGS/agent-launch.err"; die "agent launch failed"; }
  cat "$LOGS/agent-launch.json"
  local sid; sid=$(venv python -c 'import json,sys; print(json.load(open(sys.argv[1]))["session"])' "$LOGS/agent-launch.json")
  setstate AGENT_SID "$sid"
  agtermctl tree --json | grep -qi "$sid" || die "session $sid not in agtermctl tree"
  local i
  for i in $(seq 1 50); do [ -s "$CH/e2e-agent-ran" ] && break; sleep 0.2; done
  [ -s "$CH/e2e-agent-ran" ] || die "stub agent never ran in session $sid"
  grep -q "^role=$role home=$CH author=$role$" "$CH/e2e-agent-ran" || die "agent env wrong: $(cat "$CH/e2e-agent-ran")"
  carhunt agent ls
  carhunt agent close "$role" || die "carhunt agent close failed"
  for i in $(seq 1 25); do agtermctl tree --json | grep -qi "$sid" || break; sleep 0.2; done
  ! agtermctl tree --json | grep -qi "$sid" || die "session $sid still open after close"
  info "session $sid launched with the agent env and closed"
}

step_isolation() {  # nothing outside the temp HOME was touched
  if [ -s "$LOGS/blocked.log" ]; then cat "$LOGS/blocked.log"; die "blocked calls to the real Keychain / launchd"; fi
  "$_E2E_REAL_LAUNCHCTL" list | awk '{print $3}' | grep '^carhunt\.' | sort >"$W/state/launchd.after" || true
  diff "$W/state/launchd.before" "$W/state/launchd.after" || die "carhunt.* launchd jobs changed"
  [ "$(cksum_of "$REAL_HOME/.claude/settings.json")$(cksum_of "$_E2E_REAL_CLAUDE_DIR/settings.json")" = "$REAL_SETTINGS_SUM" ] \
    || die "the real Claude Code settings.json changed"
  info "no Keychain / launchd writes; real launchd labels and Claude Code settings.json unchanged"
}

run_step clone      "git clone into a temp dir"                      step_clone
run_step home       "temp HOME, scrubbed env, guard stubs"           step_home
run_step bootstrap-dry "scripts/bootstrap --dry-run changes nothing" step_bootstrap_dry
run_step bootstrap  "scripts/bootstrap ${BOOT_FLAGS[*]}"             step_bootstrap
run_step bootstrap2 "bootstrap again (idempotent)"                   step_bootstrap_again
run_step cardb      "cardb serve on a free port"                     step_cardb
run_step compose    "docker compose cardb on a free port (optional)" step_compose
run_step sweep      "carhunt sweep --sites fake --max 5 → cardb"     step_sweep
run_step web-suite  "web Playwright suite (npm run e2e)"             step_web_suite
run_step web-live   "web on the swept cardb: /health + car page"     step_web_live
run_step doctor     "carhunt doctor (all up): no fail, allowed warns" step_doctor
run_step say        "carhunt say --dry-run (no send possible)"       step_say
run_step evidence   "carhunt evidence (+ --write-asks)"              step_evidence
run_step agent      "carhunt agent launch in agterm, then close"     step_agent
run_step isolation  "no real Keychain / launchd / ~/.claude writes"  step_isolation always

[ "$FAILED" = 0 ]
