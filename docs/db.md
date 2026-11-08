# cardb — the listings database

cardb is the hub of carhunt: one SQLite-backed REST API + CLI (`cardb`) holding every car, ad, price, option, fact,
photo, message, note, verdict and the ranked "to rate" queue. Every stage (discover, contact, vet, decide, liveness)
reads and writes cars only through it. Code: [`cardb/`](../cardb/README.md) · contract: `cardb/api/openapi.yaml` ·
internals + write rules: [`cardb/DESIGN.md`](../cardb/DESIGN.md) · compose: [`deploy/`](../deploy/README.md).

## Run modes

| mode | command | when |
|---|---|---|
| local binary | `make -C cardb build` → `cardb/bin/cardb`; `cardb init` once, then `cardb serve` (127.0.0.1:8484) | development; a single Mac without Docker |
| compose | `docker compose -f deploy/compose.yaml up -d --build` (cardb :8484 + web :4321, localhost only) | default for a run: restarts itself, hardened, includes the web UI |

Both use the same data dir `$CARHUNT_HOME/cardb` (`cardb.sqlite3` + WAL, `photos/`, `tokens`) and the same
`$CARHUNT_HOME/config.yaml`. Run only one server per data dir: SQLite has one writer.
Health: `GET /healthz` (server root) and `GET /api/v1/health` — same handler, no token → `{"ok":true,"version":"…"}`.
`carhunt doctor`, `cardb healthcheck` and the compose healthcheck all probe `/healthz`.

### Build (`cardb/Makefile`)

| target | what |
|---|---|
| `make -C cardb build` | `cardb/bin/cardb` (gitignored): CGO off, `-tags nodynamic`, version from `git describe` (`VERSION=…` overrides) — same flags as the Dockerfile |
| `make -C cardb test` | `go test -count=1 ./...` |
| `make -C cardb clean` | removes `cardb/bin/` |

`scripts/bootstrap` runs `make -C cardb build`, then `cardb init`. Put `cardb/bin` on `PATH` (or `go install ./cmd/cardb`).

## `cardb init` and secrets

`cardb init [--home H] [--backend keychain|file|op] [--rotate]` (idempotent; re-run after adding a viewer):
- creates the data dir (0700) = `CARDB_DATA_DIR` > config `cardb.data_dir` > `$CARHUNT_HOME/cardb`;
- keeps valid tokens (`--rotate` makes new ones), stores each in the secrets backend and writes only their hashes to
  `<data dir>/tokens` (`name:sha256:<hex>`, 0600);
- prints names and the next step (`cardb serve` / restart), never a token. No client config file is written: the client
  finds `cardb_token` itself.

| token name | secret | env override | used by |
|---|---|---|---|
| `agents` | `cardb_token` (or `cardb.token: secret:<name>`) | `CARHUNT_SECRET_CARDB_TOKEN` | agents' CLI (author = `CARDB_AUTHOR` per session) |
| `owner.name` | `cardb_owner_token` | `CARHUNT_SECRET_CARDB_OWNER_TOKEN` | the owner's own CLI (`--token`, or `CARDB_TOKEN`) |
| each viewer | `cardb_token_<viewer>` (lowercased slug) | `CARHUNT_SECRET_CARDB_TOKEN_<VIEWER>` | that viewer: read-only + own verdict |
| — | `cardb_web_tokens` | `CARHUNT_SECRET_CARDB_WEB_TOKENS` | web: `name:token` lines, owner + every viewer (compose secret → `/run/secrets/cardb_web_tokens`) |

- Lookup (same rules as the Python `carhunt secret`): env `CARHUNT_SECRET_<NAME>` → backend. Backend: `--backend` >
  env `CARHUNT_SECRETS_BACKEND` > `secrets.backend` > keychain on macOS, file elsewhere. keychain = service
  `secrets.keychain_service` (default `carhunt`), account NAME; file = `$CARHUNT_HOME/secrets/NAME` (0600);
  op = `op://<secrets.op_vault>/NAME/password` (default vault `carhunt`).
- No command prints a value; pass one to a process with `carhunt secret exec NAME=ENVVAR -- cmd`.
- The web acts per user with that user's own token, so its writes carry the user's name and rights. There is no
  generic `web` token and no trusted-header identity.
- Legacy plain `name:token` lines in the tokens file still work (e.g. a migrated evdb), but re-run `cardb init` to hash them.

## Config (cardb + search sections)

Read at server start (restart after editing; an invalid profile refuses to start with the key path in the error, unknown
keys only warn). `cardb profile` / `GET /api/v1/profile` show the effective profile with defaults. `owner` and `secrets`
are shared with core; `search.private_sellers_abroad` and `search.price.gross` are read by discover, not cardb.

```yaml
# integrator: merge into config.example.yaml (values = defaults unless marked "example")
owner:
  name: owner                    # the human: author of web writes, needs_owner, author_kind owner; renaming keeps verdicts
  tz: Europe/Lisbon              # example; display time zone
  home: {city: Lisbon, country: PT, lat: 38.72, lon: -9.14}   # example; market home|abroad, distance, phone calling code, VAT reserve rate

cardb:
  url: http://127.0.0.1:8484     # client fallback (after --server, CARDB_URL, ~/.config/cardb/config.json)
  token: secret:cardb_token      # client token secret name
  data_dir: ~/.carhunt/cardb     # default $CARHUNT_HOME/cardb; CARDB_DATA_DIR wins
  users:                         # viewers (the owner is implicit); each gets cardb_token_<name> + a web identity
    - {name: partner, role: viewer}   # example

secrets:
  backend: keychain              # keychain | file | op (default keychain on macOS, file elsewhere)
  keychain_service: carhunt      # Keychain service name
  op_vault: carhunt              # 1Password vault for backend op

search:
  countries: []                  # ISO-2 scope; empty = any (example: [PT, ES, FR, DE])
  exclude_regions: []            # ISO 3166-2 by place names: ES-CN ES-IB FR-20R FR-971…976 GR-M IT-82 IT-88 PT-20 PT-30
  exclude_places: []             # extra city words/phrases to exclude
  price:
    max_eur: 0                   # queue: price above → out (0 = no cap); also the ×100 check without a family median
    min_eur: 0                   # price sanity floor (unset = 1500: below = lease/deposit); when set also a queue filter (price below → out)
    cap_eur: 0                   # price sanity ceiling (unset = 2 000 000)
    currency: EUR
  year_min: 0                    # queue: older → out (0 = off)
  km_max: 0                      # queue: more km → out; also fit km_ref
  powertrain: []                 # allowed fuels: bev phev hev mhev petrol diesel lpg cng hydrogen (empty = any)
  models:                        # tiers; first match wins; model "" = every family of the make
    - make: VW                   # example
      model: ID.4
      tier: 1                    # ≤ default_tier
      label: ""                  # shown with the tier
      base_fit: 0.40             # default ranking.fit.base_default (0…2)
      risk: 0                    # model risk points (known weak points)
      when:                      # all set conditions must hold; see DESIGN.md "Ranking" step 2
        power_hp: [280, 290]     # [min, max] metric hp (unknown → variant_any decides)
        drive: [fwd, rwd]        # allowed drives (awd tokens in the text count)
        variant_any: [pro]       # trim marker: whole word in model+variant
        variant_none: [gtx]      # never these words
        year_min: 2023
        year_max: 0
        battery_net_kwh: []      # [min, max]
        fuel: []
  default_tier: 0                # tier for unmatched cars (0 = highest model tier + 1)
  queue_default_tiers: []        # tiers `cardb queue` shows (empty = every tier below default_tier)
  tier_labels: {}                # tier → label, e.g. {1: "first to contact"}
  families:                      # model-family rules added to / overriding internal/store/families.yaml
    - {make: VW, make_aliases: [volkswagen], name: ID.4, match: [id4], with: [], lead: false, bare: false, body: [], body_name: ""}   # example; words folded ("ID.4" → id4)
  hard_filters:                  # queue exclusions; exactly one of field / fact(s) / flag per rule; label optional
    - {field: powertrain.battery_net_kwh, min: 70}           # numeric field out of range (missing passes)
    - {fact: deal_flag, words: [suspect], label: suspect ad} # fact contains a whole word/phrase
    - {facts: [origin, import, history_report], mentions_country: [PL, LT], label: high-risk history}  # fact names a country
    - {fact: battery_soh, min: 85}                           # numeric fact out of range
    - {flag: lease_transfer}                                 # truthy fact, or a price flag of the car's price listing
  options_wanted: {}             # option key → weight (fit, trim_score, why), e.g. {heat_pump: 3, pano: 2}
  option_labels: {}              # option key → short label in `why`
  must_have: []                  # options behind ?spec=confirmed|unknown and the unknown-option risk
  option_keys: []                # extra option vocabulary (built-ins: GET /profile option_keys)
  penalties:                     # numeric field hit → fit −weight·option_unit, trim_score −weight
    - {field: wheels_in, min: 20, weight: 2, label: '{v}" wheels'}   # example
  weights: {value: 1, fit: 1, risk: 1}   # score = value·v·fit − risk·r; fit scales the fit terms
  road_factor: 1.3               # great-circle → road km (1…3)
  ranking:
    peers:
      power_band_hp: 25          # trim = power rounded to this + awd/2wd
      km_bands: [15000, 30000]   # km band upper bounds
      min_n: [8, 6, 3, 3]        # ladder: trim+year+km, trim+year, trim, family
      year_eur: 2000             # peer price adjust per model year (steps 2-4)
      km_eur: 0.06               # … per km
      outlier_min_n: 8           # band size before the outlier screen
      outlier_low: 0.67          # drop asks below × band median
      outlier_high: 1.65         # … above
    landed_cost:
      default_distance_km: {}    # country → km when a car has no distance; "other" = any (else centroid estimate, else 2500 abroad)
      home_trip: [[100, 50], [500, 100], [0, 200]]   # [max_km, €] steps; 0 = any distance
      abroad_trip:
        travel: [[700, 50], [0, 100]]
        fixed: 250               # export plates + insurance
        energy_per_km: 0.10
        tolls_per_km: 0.035
        night_cost: 100
        night_free_km: 700
        km_per_night: 1300
        max_nights: 2
        food: [[700, 30], [0, 60]]
      registration_home: 65
      registration_import: 250
    vat_reserve:                 # abroad "new means of transport" → VAT due at home
      enabled: true
      pct: null                  # default = owner.home.country standard VAT rate (0…50)
      km_max: 6000
      months_max: 6
    fit:
      base_default: 0.40
      option_unit: 0.03          # per options_wanted / penalty weight point
      seller_private: 0.06
      seller_reseller: -0.12
      home_market: 0.04
      age_per_year: 0.005        # × max(0, age_years − age)
      age_years: 8
      km: 0.03                   # × (1 − km / km_ref)
      km_ref: 0                  # 0 = search.km_max, else 50000
      history_fact: 0.015        # each: one owner, service history, accident-free
    risk:                        # points
      unknown_option: 0.8        # each must_have / top wanted option not yes/no
      unknown_option_top: 4      # how many options_wanted (by weight) count
      no_vin: 0.8
      no_service_history: 0.8
      no_owners: 0.5
      no_accidents: 0.8
      no_health: 1
      health_facts:              # fuel → fact keys; any one present = health known
        bev: [battery_soh, soh, battery_health, battery_report, battery_cert, battery_test]
        phev: [battery_soh, soh, battery_health, battery_report, battery_cert, battery_test]
      distance_unknown: 0.5
      reseller: 4
      vat_reserve: 4
      thin_peers: 3
      thin_peers_n: 8
      spread: 3
      spread_max: 0.15           # (IQR75 − IQR25) / fair_landed
      red_flag: 3                # each red_flags item
      price_forced: 0.5
      reasons_max: 5             # risk_reasons shown
```

Worked example: the EV run's profile is `cardb/internal/profile/testdata/ev.yaml` (VAG 286 hp RWD = tier 1 via
`power_hp` + `variant_any` markers, long-range alternatives = tier 2, islands excluded, PL/Baltic history and suspect ads
filtered, e-seats + power tailgate as `must_have`, per-country default distances).

## API and CLI

Base `/api/v1`, `Authorization: Bearer <token>` (header only, never in a URL). Errors `{error}` (+ `reason`/`version`
details on 422/412). Main entry point for agents: `POST /listings/upsert`. Full list: `cardb/api/openapi.yaml`;
every flag: `cardb help COMMAND`.

| task | CLI | API |
|---|---|---|
| record an ad | `cardb upsert --url U --price … --fuel bev --opt k=v:src` | `POST /listings/upsert` |
| photos | `cardb photo add CAR FILE --listing ID` | `POST /cars/{car}/photos` |
| find by URL | `cardb find-listing URL` (exit 3 = none) | `GET /listings?url=` |
| log a message | `cardb msg --to CONTACT --channel C --dir in\|out TEXT` | `POST /messages` |
| facts / options | `cardb fact CAR k=v:src` · `cardb opt CAR k=v:src` | `PUT /cars/{car}/facts/{key}` |
| edit safely | `cardb show CAR --json` → `cardb set CAR … --if-version N` · `--red-flag-add T` | `PATCH /cars/{car}` + `If-Match` |
| status / flags | `cardb status CAR S --if-version N` · `needs-owner CAR "why"` · `deal CAR on` | `POST …/status` · `PUT …/good-deal` |
| rate | `cardb verdict CAR up\|maybe\|down [--user U]` | `PUT /cars/{car}/verdict` |
| browse | `cardb ls … [--fuel F] [--sort score]` · `show CAR` · `queue [--user U]` · `profile` | `GET /cars` · `/cars/{car}` · `/queue` · `/profile` |
| ad gone | (liveness checker only) | `PATCH /listings/{id}` + `ad_check` event |
| ops | `cardb stats` · `activity --since 24h` · `health` · `backup DEST` | `GET /stats` · `/activity` · `/healthz` |

## Rules for agents (with why)

- **Send the version back.** Read `version` (`cardb show CAR --json`), then `cardb set|status CAR … --if-version N`.
  On `conflict: car changed (version M)` (exit 1, HTTP 412): re-read, re-decide on the new state, retry. WHY: concurrent
  agents overwrote each other and a car's status lagged its chat.
- **List fields: `--red-flag-add/-rm`, `--question-add/-rm`** (exact text, atomic). `--red-flag`/`--question` replace the
  whole list and drop other agents' items.
- **Price rejected (exit 1, `price_x100|price_lease|price_net|price_range`)?** Re-read the ad: cents, a monthly rate,
  a net price? Fix the number, or pass `--price-vat gross|net|margin` when the ad states it. `--force` only after
  checking — the price is stored flagged and the car leaves the fair-price pool. WHY: 10 ×100 prices in the EV run.
- **Powertrain: nested is the contract** (`powertrain{fuel, battery_net_kwh, …}`; CLI `--fuel --battery-net
  --engine-cc --gearbox --wltp-range …`). Flat `battery_net_kwh` in upsert JSON is still accepted (422 when it
  disagrees with the nested value). Fuel/gearbox accept ad words in seven languages (`elétrico`, `plug-in`, `gasóleo`,
  `GPL`, `automático`, `DSG`, …); an unknown word is 400.
- **Record the fuel.** Two different known fuels never dedupe (no link, no proposal; `mhev` is compatible with
  petrol/diesel/hev), so a correct fuel keeps a petrol twin of an EV apart; VIN/plate still win.
- Upsert without photos, then `photo add --listing`; resolve later writes by `find-listing URL`, never a stored car id.
- `--json` + jq and argument arrays in scripts; log every message the moment it is sent or read, verbatim.

## Authors, users, verdicts

- Every write has an author: body `author` > `X-Author` (`--author`, `CARDB_AUTHOR`) > token name.
  `carhunt agent launch` sets `CARDB_AUTHOR=<role>`, so each write is traceable to an agent.
- `author_kind`: `owner` (= `owner.name`) · `viewer` (a `cardb.users` entry) · `import` (author `import…`) · `agent`.
- Users = owner + viewers. Verdicts are per user (`up|maybe|down` + note, history as `verdict` events). Cars show the
  owner's verdict unless `?user=` / `--user`; `verdicts` lists everyone's. The queue is per user (default owner).
- A viewer token is read-only except for that viewer's own verdict (403 otherwise). WHY: a second household member had
  no identity in the EV run, so their opinions lived in chat.

## Ranking, price sanity, versions

Details and every formula: [`cardb/DESIGN.md`](../cardb/DESIGN.md) "Ranking", "Price sanity", "Versions".
- Queue = per user: unrated, open status, a live ad, in scope (missing values pass, shown as `? km`). Tier from
  `search.models`; then good deal, `deal_rank` fact, **score** = w.value·value·fit − w.risk·risk, landed price.
- value = landed price vs the peer group's fair landed price (median of per-country medians); fit = wanted options,
  seller, home market, age, km, history; risk = missing evidence, thin/wide peers, red flags, model risk, VAT reserve.
  Agents feed facts (`deal_rank`, `trim_score`, history, health facts), never scores.
- Price sanity bounds: `search.price.min_eur` (default 1500), `cap_eur` (2 000 000), 8× family median / `max_eur`.
- `version` is opaque: compare it, never compute it; it moves on any write to the car or anything on its page.

## Remote access

The compose ports bind to `127.0.0.1`. To reach cardb from a phone or another machine pick one:

| option | how | notes |
|---|---|---|
| **Tailscale (recommended)** | `tailscale serve --bg --https=443 http://127.0.0.1:4321` (web) and `tailscale serve --bg --https=8443 http://127.0.0.1:8484` (API); **Funnel off** | tailnet-only, TLS + device auth for free; agents elsewhere set `CARDB_URL=https://<host>.<tailnet>.ts.net:8443` |
| TLS reverse proxy (Caddy) | public host, `/api/*` + `/healthz` → `127.0.0.1:8484`, the rest → `127.0.0.1:4321`, `request_body max_size 50MB` (photo uploads) | the API's bearer token is the gate for `/api`; put the web behind its own login (Caddy `basic_auth` on the web routes only) |

- **Never put an interactive login (forward-auth/SSO) in front of `/api/*`.** Bearer clients (CLI, agents, scripts) can't
  complete it. WHY: in the EV run off-LAN agents were locked out by exactly that.
- Don't expose the API without TLS: the token travels in a header.
- Web identity = the per-user tokens in `cardb_web_tokens`; a proxy login in front of the web only gates access.

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
| DB snapshot | compose: `docker compose -f deploy/compose.yaml exec cardb cardb backup /data/snapshot-$(date +%F).sqlite3`, then move it out of the data dir · local: `cardb backup DEST` (data dir as for `serve`) |
| photos | copy `$CARHUNT_HOME/cardb/photos/` (content-addressed, append-only: incremental tools like restic/rsync are cheap) |
| restore | stop the server; replace `cardb.sqlite3` with the snapshot, delete `cardb.sqlite3-wal`/`-shm`; restore `photos/`; start |

`backup` uses `VACUUM INTO`: consistent while the server writes; copying the live `.sqlite3` file is not. Move snapshots
off the machine (they hold seller data — never into the repo).

## Backfill protocol (any data repair or bulk inference)

1. **Snapshot**: `cardb backup` → keep the file.
2. **Plan**: a script reads via the API/DB and writes a plan JSON (car id, field, old → new, evidence) — no writes.
3. **Rehearse on a copy**: run the plan against a copy of the snapshot (copy of the data dir: `cardb serve --data <copy> --listen 127.0.0.1:8485`); check counts and a sample by hand.
4. **Live**: apply through the API (or inside one transaction per car that re-checks the inputs); fill unknowns only;
   inferred values carry their own source (`rule:<name>`) + an event per car.
5. **Replay = 0 changes**: run it again; any write means it isn't idempotent — stop and fix.
6. **`PRAGMA quick_check`**: take a fresh `cardb backup`, then `sqlite3 <snapshot> 'PRAGMA quick_check'` → `ok`.

WHY: the EV run used this for the drive backfill, the good-deal backfill and the photo-dedupe repair (47 listings
re-split after stock photos merged different cars). The drive rule once said RWD where the ad title said AWD: read the
raw text before trusting a `rule:*` value, and never overwrite a stronger source.

## Migrating an evdb data dir

1. Stop evdb and take a snapshot (`evdb backup`); work on a copy.
2. Copy the data dir to `$CARHUNT_HOME/cardb/` (keep `photos/`) and rename `ev.sqlite3` → `cardb.sqlite3`.
3. Set `owner.name` in config to the name the old setup used for the buyer (the old web's forced author), then
   `cardb init` for fresh hashed tokens (old `name:token` lines still work meanwhile).
4. Start cardb. Migrations run once (`PRAGMA user_version`):
   - `needs_<person>`(`_reason`) → `needs_owner`(`_reason`), `km_to_<city>` → `distance_km`;
   - powertrain columns added; a car with a battery value and no fuel gets `fuel = bev` (the old schema was EV-only);
   - `version` starts counting; listings get `price_vat` + empty `price_flags` (old prices are not re-checked);
   - users table; every old single verdict becomes the owner's;
   - legacy owner identity rewrite (every start, idempotent): option/fact `source`, message `sender_kind` and note
     `author_kind` equal to lower(`owner.name`) become `owner` — so step 3's name must match exactly (case-insensitive).
5. Check: `cardb stats` matches the old counts; `PRAGMA quick_check` on a fresh snapshot = `ok`; `cardb queue` and a few
   cars in the web UI look right (tiers now come from `search.models` — port the old tier rules into config first).

## Known gaps

- Liveness and cross-URL dedupe depend on per-site URL rules (`normalize.go`); a new site without one dedupes by full URL only.
- Server-side photo URL fetch has no SSRF allowlist and is blocked by many sites; photos mostly come from browser helpers.
- `deal_rank` / `trim_score` are facts parsed by format (`T<tier>-<n>`); a typo sorts as unparseable.
- `DELETE /cars` is a hard cascade, guarded only by `?confirm=id` / `--yes`.
- The profile is read at start: config edits need a server restart.
- No i18n: UI text is English; times display in `owner.tz`.
- One server per data dir; no replication (SQLite + file backups only).
