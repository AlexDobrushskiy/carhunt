# cardb — the listings database

cardb is the hub of carhunt: one SQLite-backed REST API + CLI (`cardb`) holding every car, ad, price, option, fact,
photo, message, note, verdict and the ranked "to rate" queue. Every stage (discover, contact, vet, decide, liveness)
reads and writes cars only through it. Code: [`cardb/`](../cardb/README.md) · contract: `cardb/api/openapi.yaml` ·
internals + write rules: [`cardb/DESIGN.md`](../cardb/DESIGN.md) · compose: [`deploy/`](../deploy/README.md).

## Run modes

| mode | command | when |
|---|---|---|
| local binary | `cardb init` once, then `cardb serve` (127.0.0.1:8484) | development; a single Mac without Docker |
| compose | `docker compose -f deploy/compose.yaml up -d --build` (cardb :8484 + web :4321, localhost only) | default for a run: restarts itself, hardened, includes the web UI |

Both use the same data dir `$CARHUNT_HOME/cardb` (`cardb.sqlite3` + WAL, `photos/`, `tokens`) and the same
`$CARHUNT_HOME/config.yaml`. Run only one server per data dir: SQLite has one writer.
Health: `GET /healthz` and `GET /api/v1/health` (same handler, no token) → `{"ok":true,"version":"…"}`.

## `cardb init` and secrets

`cardb init` creates `$CARHUNT_HOME/cardb/`, generates the tokens, writes their hashes to `$CARHUNT_HOME/cardb/tokens`
(`name:sha256:<hex>`, 0600) and stores the plain values through the secrets backend (`secrets.backend` in config). It
prints only the next step, never a token. Re-running keeps existing tokens.
<!-- TODO(lead): exact init flags (--force/--rotate?) and token set after merging mod/db-users -->

| token (name) | secret name | env override | used by |
|---|---|---|---|
| `owner` <!-- TODO(lead): owner token name = owner.name? --> | `cardb_owner_token` <!-- TODO(lead) --> | `CARHUNT_SECRET_CARDB_OWNER_TOKEN` | the owner's own CLI |
| `agents` | `cardb_token` | `CARHUNT_SECRET_CARDB_TOKEN` | agents' CLI (author = `CARDB_AUTHOR` per session) |
| `web` + viewers | `cardb_web_token` | `CARHUNT_SECRET_CARDB_WEB_TOKEN` | web server (compose secret) |

Lookup order (client and `carhunt secret`): env `CARHUNT_SECRET_<NAME>` → Keychain service `carhunt` account `<name>` →
`$CARHUNT_HOME/secrets/<name>` (0600), per `secrets.backend`. No command prints a value; pass one to a process with
`carhunt secret exec NAME=ENVVAR -- cmd`. Legacy `name:token` lines in the tokens file still work (e.g. a migrated evdb).

## Config keys (`$CARHUNT_HOME/config.yaml`)

Read once at server start (restart after editing). `GET /api/v1/profile` shows the effective profile (no secrets).

| section.key | meaning |
|---|---|
| `owner.name` | the human: default author of web writes, `needs_owner`, `author_kind=owner` |
| `owner.tz` · `owner.languages` | display time zone · languages the owner reads |
| `owner.home{city,country,lat,lon}` | `distance_km` estimates, `market` home/abroad, default calling code for phones |
| `cardb.url` · `cardb.token` | client: server URL · `secret:cardb_token` reference |
| `cardb.data_dir` | `cardb init` / local serve data dir (default `$CARHUNT_HOME/cardb`) |
| `cardb.users[{name, role}]` | viewers (role `viewer`); the owner is implicit |
| `search.countries` · `exclude_regions` (ISO 3166-2) · `exclude_places` | scope; hard filters |
| `search.price{max_eur,min_eur,gross,currency}` · `year_min` · `km_max` · `powertrain` | hard filters (+ price sanity bounds) |
| `search.hard_filters[]` | extra exclusions: `{field, min/max}`, `{fact(s), words}`, `{flag, exclude}` |
| `search.models[{make, model, tier, label, base_fit, risk, when}]` | tiers: first match wins; `when{power_hp, drive, variant_any, variant_none, year_min, battery_net_kwh, fuel}` |
| `search.default_tier` · `queue_default_tiers` | tier for unmatched cars (3) · tiers `cardb queue` shows by default |
| `search.families[]` | extra model-family recognition rules (data, not Go) |
| `search.options_wanted{key: weight}` · `must_have` · `option_keys` · `penalties[]` | fit + `spec=` filter + extra option vocabulary |
| `search.weights{value, fit, risk}` · `road_factor` | score weights · great-circle → road km |
| `search.ranking.*` | peer ladder, landed cost, VAT reserve, risk weights (defaults below) |

<!-- TODO(lead): exact search.ranking.* key names and defaults from mod/db-rank -->

Worked example (the EV run's tiers, as profile data — no buyer constant lives in Go):

```yaml
search:
  models:
    - {make: Volkswagen, model: "ID.4", tier: 1, when: {power_hp: [280, 290], drive: [rwd, fwd], variant_any: [pro], variant_none: [gtx, pure], year_min: 2023}}
    - {make: Audi, model: Q4, tier: 1, when: {power_hp: [280, 290], drive: [rwd, fwd], variant_any: ["45"], variant_none: [sq4, quattro], year_min: 2024}}
    - {make: Skoda, model: Enyaq, tier: 1, when: {power_hp: [280, 290], drive: [rwd, fwd], variant_any: ["85"], variant_none: [85x, rs]}}
    - {make: Hyundai, model: "Ioniq 5", tier: 2, when: {battery_net_kwh: [74, 85]}}
    - {make: Kia, model: EV6, tier: 2, when: {variant_none: [gt, gtline]}}
  default_tier: 3
  queue_default_tiers: [1, 2]
  exclude_regions: [PT-20, PT-30, ES-CN]          # islands: transport + paperwork
  hard_filters:
    - {facts: [origin, import, history_report], words: [Poland, Lithuania, Latvia, Estonia]}   # odometer-fraud markets
    - {flag: lease_transfer, exclude: true}
```

Power known → power decides; unknown → `variant_any` tokens stand in (the trim marker). <!-- TODO(lead): verify `when`/hard_filters syntax against mod/db-rank -->

## API and CLI

Base `/api/v1`, `Authorization: Bearer <token>` (header only, never in a URL). Errors `{error}`. Main entry point for
agents: `POST /listings/upsert` (idempotent by normalized URL / site ad id). Full list: `cardb/api/openapi.yaml`.

| task | CLI | API |
|---|---|---|
| record an ad | `cardb upsert --url U --price … --opt k=v:src` | `POST /listings/upsert` |
| photos | `cardb photo add CAR FILE --listing ID` | `POST /cars/{car}/photos` |
| find by URL | `cardb find-listing URL` (exit 3 = none) | `GET /listings?url=` |
| log a message | `cardb msg --to CONTACT --channel C --dir in\|out TEXT` | `POST /messages` |
| facts / options | `cardb fact CAR k=v:src` · `cardb opt CAR k=v:src` | `PUT /cars/{car}/facts/{key}` |
| status / flags | `cardb status CAR S` · `needs-owner CAR "why"` · `deal CAR on` | `POST …/status` · `PATCH /cars/{car}` · `PUT …/good-deal` |
| rate | `cardb verdict CAR up\|maybe\|down` | `PUT /cars/{car}/verdict` |
| browse | `cardb ls …` · `cardb show CAR` · `cardb queue` | `GET /cars` · `GET /cars/{car}` · `GET /queue` |
| ad gone | (liveness checker only) | `PATCH /listings/{id}` + `ad_check` event |
| ops | `cardb stats` · `activity --since 24h` · `health` · `backup DEST` | `GET /stats` · `/activity` · `/healthz` |

Scripts: `--json` + jq, argument arrays (never string-built shell). Exit codes 0 ok · 1 API/network · 2 usage · 3 not found.

## Authors, users, verdicts

- Every write has an author: body `author` > `X-Author` (`--author`, `CARDB_AUTHOR`, `AGTERM_SESSION_ID`) > token name.
  `carhunt agent launch` sets `CARDB_AUTHOR=<role>`, so each write is traceable to an agent.
- `author_kind`: `owner` (= `owner.name`) · `viewer` (a `cardb.users` entry) · `agent` · `import`.
- Users = owner + viewers. Verdicts are per user (`up|maybe|down` + note, history as `verdict` events). Cars show the
  owner's verdict unless `?user=`; `verdicts` lists everyone's. The queue is per user (default owner): rating a car takes it out.
- A viewer token is read-only except for that viewer's own verdict (403 otherwise). WHY: a second household member had no
  identity in the EV run, so their opinions lived in chat.

## Ranking (the queue)

One pure server-side function from profile + data; API, CLI and web show the same order. Details: DESIGN.md "Ranking".
- Eligible: no verdict from the user, not closed/dropped/bought, a live ad, all hard filters (missing value passes, shown as `? km`).
- Tier from `search.models`. Within a tier: good deal, then `deal_rank` fact, then **score** = w.value·value·fit − w.risk·risk.
- value: landed price (price + trip + registration + VAT reserve) vs the peer group's fair landed price (median of
  per-country medians; peers by family → trim → year → km band). fit: wanted options, seller type, home market, age, km,
  history facts. risk: missing evidence (VIN, service history, powertrain health, must-have options), thin/wide peer group,
  red flags, model risk, VAT reserve, reseller.
- Agents feed it facts (`deal_rank`, `trim_score`, history facts), never scores. WHY: one ranking, in one place.

## Price sanity

Upsert and `PATCH /listings/{id}` refuse a price that looks ×100 (cents), like a monthly/lease rate, net of VAT, or out of
the plausible range: HTTP 422 `{error, reason: price_x100|price_lease|price_net|price_range, expected}`. Check the ad,
then resend with `force` to store it anyway: it keeps `price_flags` + a `price_sanity_override` event and adds ranking risk.
Prices are integer, gross (incl. VAT); `price_vat: net` is refused unless forced. WHY: 10 ads were stored ×100 in the EV
run and sorted as bargains. <!-- TODO(lead): thresholds + CLI flag name from mod/db-schema -->

## Versions and If-Match

Each car has `version` (+1 on every car write); `GET /cars/{car}` sends `ETag: "<version>"`. `PATCH /cars/{car}` and
`POST …/status` with `If-Match: "<version>"` (or body `version`) return 412 + the current car when someone wrote in
between — re-read, re-decide, retry. Without If-Match the write applies (last writer wins). List fields: use
`red_flags_add/_remove`, `open_questions_add/_remove` (atomic), not a full-list PATCH. WHY: concurrent agents dropped each
other's red flags and a car's status lagged its chat.

## Remote access

The compose ports bind to `127.0.0.1`. To reach cardb from a phone or another machine pick one:

| option | how | notes |
|---|---|---|
| **Tailscale (recommended)** | `tailscale serve --bg --https=443 http://127.0.0.1:4321` (web) and `tailscale serve --bg --https=8443 http://127.0.0.1:8484` (API); **Funnel off** | tailnet-only, TLS + device auth for free; agents elsewhere set `CARDB_URL=https://<host>.<tailnet>.ts.net:8443` |
| TLS reverse proxy (Caddy) | public host, `/api/*` + `/healthz` → `127.0.0.1:8484`, the rest → `127.0.0.1:4321`, `request_body max_size 50MB` (photo uploads) | the API's bearer token is the gate for `/api`; put the web behind its own login (Caddy `basic_auth` on the web routes only) |

- **Never put an interactive login (forward-auth/SSO) in front of `/api/*`.** Bearer clients (CLI, agents, scripts) can't
  complete it. WHY: in the EV run off-LAN agents were locked out by exactly that.
- Don't expose the API without TLS: the token travels in a header.
- A web proxy that authenticates users may pin the identity with a trusted header (`CARDB_WEB_USER_HEADER`). <!-- TODO(lead): confirm with mod/web -->

```caddyfile
cardb.example.invalid {
	request_body { max_size 50MB }
	handle /api/* { reverse_proxy 127.0.0.1:8484 }
	handle /healthz { reverse_proxy 127.0.0.1:8484 }
	handle {
		basic_auth { owner <bcrypt-hash> }
		reverse_proxy 127.0.0.1:4321
	}
}
```

## Backups

| what | how |
|---|---|
| DB snapshot | compose: `docker compose -f deploy/compose.yaml exec cardb cardb backup /data/backups/cardb-$(date +%F).sqlite3` · local: `CARDB_DATA_DIR=$CARHUNT_HOME/cardb cardb backup DEST` |
| photos | copy `$CARHUNT_HOME/cardb/photos/` (content-addressed, append-only: incremental tools like restic/rsync are cheap) |
| restore | stop the server; replace `cardb.sqlite3` with the snapshot, delete `cardb.sqlite3-wal`/`-shm`; restore `photos/`; start |

`backup` uses `VACUUM INTO`: consistent while the server writes; copying the live `.sqlite3` file is not. Move snapshots
off the machine (they hold seller data — never into the repo).

## Backfill protocol (any data repair or bulk inference)

1. **Snapshot**: `cardb backup` → keep the file.
2. **Plan**: a script reads via the API/DB and writes a plan JSON (car id, field, old → new, evidence) — no writes.
3. **Rehearse on a copy**: run the plan against a copy of the snapshot (`cardb serve --data <copy>` on another port); check counts and a sample by hand.
4. **Live**: apply through the API (or inside one transaction per car that re-checks the inputs); fill unknowns only;
   inferred values carry their own source (`rule:<name>`) + an event per car.
5. **Replay = 0 changes**: run it again; any write means it isn't idempotent — stop and fix.
6. **`PRAGMA quick_check`**: take a fresh `cardb backup`, then `sqlite3 <snapshot> 'PRAGMA quick_check'` → `ok`.

WHY: the EV run used this for the drive backfill, the good-deal backfill and the photo-dedupe repair (47 listings
re-split after stock photos merged different cars). The drive rule once said RWD where the ad title said AWD: read the
raw text before trusting a `rule:*` value, and never overwrite a stronger source.

## Migrating an evdb database

1. Stop evdb. Snapshot it (`evdb backup`) and work on the copy.
2. Copy the data dir to `$CARHUNT_HOME/cardb/` and rename `ev.sqlite3` → `cardb.sqlite3`; keep `photos/` as is.
3. Tokens: legacy `name:token` lines work in `$CARHUNT_HOME/cardb/tokens`; better: run `cardb init` for fresh hashed tokens.
4. Start cardb: migrations run once (`PRAGMA user_version`): legacy `needs_<person>` → `needs_owner`, `km_to_<city>` →
   `distance_km`, battery columns → powertrain, the single verdict → the owner's verdict.
   <!-- TODO(lead): confirm powertrain + users data migration behaviour from mod/db-schema / mod/db-users -->
5. Check: `cardb stats` matches the old counts; `PRAGMA quick_check` = ok; spot-check a few cars in the web UI.
6. Set `owner.name` in config to the old owner author (e.g. the name the old web forced) so old notes/verdicts map to the owner.

## Known gaps

- Liveness and cross-URL dedupe depend on per-site URL rules (`normalize.go`); a new site without one dedupes by full URL only.
- Server-side photo URL fetch has no SSRF allowlist and is blocked by many sites; photos mostly come from browser helpers.
- `deal_rank` / `trim_score` are facts parsed by format (`T<tier>-<n>`); a typo sorts as unparseable.
- `DELETE /cars` is a hard cascade, guarded only by `?confirm=id` / `--yes`.
- No i18n: UI text is English; times display in `owner.tz`.
- One server per data dir; no replication (SQLite + file backups only).
