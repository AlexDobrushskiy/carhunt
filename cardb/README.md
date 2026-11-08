# cardb

The carhunt listings database: cars (physical vehicles), their ads on any marketplace, price history, options and facts
with evidence, photos, timeline events, seller chat, notes and per-user verdicts — plus the ranked "to rate" queue.
A Go REST API over SQLite and one binary, `cardb`, that is both the server and the CLI agents use to record everything.
Every carhunt stage reads and writes car data only through cardb.

- Contract: [`api/openapi.yaml`](api/openapi.yaml) (wire types `internal/api/types.go`)
- Design (storage, dedupe, merge/split, ranking, write rules with their why): [`DESIGN.md`](DESIGN.md)
- Operating it (compose, remote access, backups, backfills): [`../docs/db.md`](../docs/db.md)

## Install and run

```sh
make -C cardb build           # → cardb/bin/cardb (static, version-stamped; Go 1.26+). Also: make test, make clean
export PATH="$PWD/cardb/bin:$PATH"
cardb init                     # data dir + tokens (secrets backend; hashes in <data dir>/tokens); idempotent, --rotate
cardb serve                    # 127.0.0.1:8484, data dir + profile from $CARHUNT_HOME
cardb health
```

Or in Docker: `docker compose -f deploy/compose.yaml up -d --build cardb` (see [`../deploy/README.md`](../deploy/README.md)).
Token and secret names, `init` flags: [`../docs/db.md`](../docs/db.md#cardb-init-and-secrets).

### Server

| env | default | what |
|---|---|---|
| `CARDB_LISTEN` | `127.0.0.1:8484` | listen address (`0.0.0.0:8484` inside the container) |
| `CARDB_DATA_DIR` | config `cardb.data_dir` (relative to `$CARHUNT_HOME`; best omitted), else `$CARHUNT_HOME/cardb` | `cardb.sqlite3` (WAL) + `photos/` + `tokens` |
| `CARDB_TOKENS_FILE` / `CARDB_TOKENS` | `<data dir>/tokens` | named tokens: `name:sha256:<hex>` lines from `cardb init`, or legacy `name:token` |
| `CARHUNT_CONFIG` / `CARHUNT_HOME` | `~/.carhunt/config.yaml` | buyer profile (`owner`, `search`, `cardb` sections); missing = neutral profile |

`cardb backup DEST.sqlite3` (VACUUM INTO snapshot, run where the data dir is) · `cardb healthcheck` (container probe).

### Client

| setting | flag | env | config file key |
|---|---|---|---|
| server URL | `--server` | `CARDB_URL` | `url`, then carhunt config `cardb.url`, then `http://127.0.0.1:8484` |
| token | `--token` | `CARDB_TOKEN`, then secret `cardb_token` (`CARHUNT_SECRET_CARDB_TOKEN` → secrets backend) | never stored there |
| author | `--author` | `CARDB_AUTHOR` | `author`, else the server uses the token name |

Client config file: `~/.config/cardb/config.json` (`$CARDB_CONFIG`), url + author only. `carhunt agent launch` sets
`CARDB_AUTHOR=<role>` so every write is attributable. The owner's own CLI uses `CARDB_TOKEN` = the `cardb_owner_token` secret
(e.g. `carhunt secret exec cardb_owner_token=CARDB_TOKEN -- cardb verdict 12 up`).

## Conventions (for agents)

- `CAR` = numeric id or any alias/slug. A merged car's old id still resolves. Before a write by number, `show` the car:
  aliases look like ids (`12` is car 12, not the car aliased `abroad-12`).
- Scripts use `--json` + jq; table output is for humans. On failure stdout is empty and stderr carries
  `{"error", "exit_code", "status"}`. Exit codes: `0` ok · `1` API/network · `2` usage · `3` not found.
- Build argument arrays (Python, `"$@"`), not string-built shell: zsh `${x:+--flag $x}` doesn't word-split and silently
  drops writes.
- Flags go before or after positional args; text starting with `-` goes after `--`.
- Writes are idempotent (upsert by URL/site ad id, `msg` by external id/key/near duplicate, `event --key`, photos by hash):
  retrying is safe.
- Re-upserting a removed/sold ad relists it unless `--seen-at` is older than the removal: pass `--seen-at` when replaying.
- Numbers are lenient (`--price "34 600 €"`, `--km 31.200`, `--reg 07/2023`). Times: RFC 3339 or local `"2026-11-01 14:05"`.
- Prices are integer, gross (incl. VAT). A price that looks ×100, like a lease rate, or net is refused (exit 1, HTTP 422
  with a `reason`); check the ad, fix the number or pass `--price-vat gross|net|margin`; `--force` only after checking (stored flagged, the car leaves the fair-price pool).
- Concurrent edits: read `version` (`show CAR --json`), then `set`/`status … --if-version N`; on `conflict: car changed
  (version M)` (exit 1, HTTP 412) re-read, re-decide, retry. Use `--red-flag-add/-rm` and `--question-add/-rm`;
  `--red-flag`/`--question` replace the whole list.
- Powertrain: `--fuel --battery-net --battery-gross --engine-cc --gearbox --wltp-range --wltp-consumption --co2` (nested
  `powertrain` in JSON; flat `battery_*_kwh` still accepted). Fuel/gearbox take ad words (`elétrico`, `plug-in`,
  `gasóleo`, `DSG`, …). Record the fuel: two different known fuels never dedupe (`mhev` ≈ petrol/diesel/hev).
- Photos are recognised by content (JPEG incl. `.jfif`, PNG, GIF, WebP, HEIC/HEIF, AVIF); non-images are refused (exit 2).

### Evidence arguments

Options and facts take `key=value[:source[:ref]]`:

```
pano=yes:ad_text:"Panoramic roof"     heat_pump=no:vin_pr_code:SYN1
warranty=to 2028-11:seller_said        owners=1:ad_spec
```

Option values `yes|no|unknown` (`y/n/?`). Sources: `ad_text ad_spec photo vin_pr_code vin_decoder seller_said inspection
agent_inference owner`. The first `:`-segment that is a known source is the source, so fact values may contain `:`.
Known option keys = built-in list + `search.option_keys` (`GET /api/v1/profile`); others are stored with a warning.

## Typical agent flow

```sh
# 1. Record an ad (re-run any time; same URL = same listing). Prints car id, listing id, duplicate candidates.
cardb upsert --url "https://listings.example.invalid/ad/SYN-1001" \
  --price 31900 --make Volkswagen --model "ID.4" --variant "Pro" --fuel bev --reg 2023-05 --km 31200 \
  --country PT --city Lisbon --seller-name "SYNTH Motors" --seller-type dealer --phone "+351 555 010 203" \
  --opt pano=yes:ad_text:"Panoramic roof" --opt heat_pump=unknown

# 2. Photos after the upsert, tied to the listing; later writes resolve the car by URL, never a stored id.
cardb photo add "$(cardb find-listing https://listings.example.invalid/ad/SYN-1001 --json | jq .car_id)" ./cover.jpg --listing 7

# 3. Log every message at once, verbatim (car found by the seller's number).
cardb msg --to 351555010203 --channel whatsapp --dir out "Hello, is the car still available?"
cardb msg --to 351555010203 --channel whatsapp --dir in --at "2026-11-01 14:20" "Yes, it is." --attach ./vin-plate.jpg

# 4. What you learned.
cardb fact 12 warranty="to 2028-11:seller_said" battery_soh=94%:seller_said
cardb set 12 --vin SYNTEST0000000001
cardb event 12 --type vin_check --summary "decoder: no heat pump" --data '{"codes":["SYN1"]}' --key vin-12
cardb status 12 talking --reason "seller answered"
cardb needs-owner 12 "seller offers a test drive Saturday 10:00 — confirm?"

# 5. Look things up.
cardb ls --status talking,ready_to_visit --opt pano:yes --max-price 36000
cardb queue --limit 20
cardb show 12
```

## CLI reference

Global: `--json`, `--server URL`, `--token T`, `--author A` (anywhere). `cardb help COMMAND` lists every flag — it is the
source of truth; this table is generated from `cardb help` and summarized.

### Listings

| command | what |
|---|---|
| `upsert --url URL [flags]` | POST /listings/upsert. Spec: `--make --model --variant --body --reg --km --power-kw --drive --seats --colour --interior --interior-tone --wheels --vin --plate --country --city --distance-km`; powertrain: `--fuel --battery-net --battery-gross --engine-cc --gearbox --wltp-range --wltp-consumption --co2`. Listing: `--site --title --price --price-note --price-vat --force --removed --sold --listing-status --seen-at --raw-json`. Seller: `--seller-name --seller-type --seller-company --seller-city --seller-note --phone… --whatsapp… --email… --contact KIND:VALUE…`. Car: `--slug --alias… --status --summary --car REF --overwrite`. Evidence: `--opt… --fact… --source`. `--photo PATH\|URL…` (uploaded after the upsert with the listing id). Car fields fill only empty values unless `--overwrite`. |
| `upsert --from-json FILE\|-` | Full ListingUpsert object or an array (per-item results, exit 1 if any failed). |
| `find-listing URL` | GET /listings?url= (exit 3 if none). |
| `listing show ID` · `listing set ID [--status S] [--price N] [--price-note T] [--price-vat V] [--force]` | One listing / change its status or price (price sanity as on upsert). |

### Cars

| command | what |
|---|---|
| `ls [QUERY] [filters]` | Table (id, status, verdict, title, year, km, hp, price, place, sites, flags). Filters: `--status… --verdict… --make --model --family… --q --country… --max-km --min-price --max-price --min-hp --max-hp --drive… --fuel… --year-min --year-max --max-dist --seller-type… --opt key:value… --needs-owner --good-deal --tier… --dupes --market home\|abroad --user U --sort (… score) --order --limit --offset`. Repeatable filters take comma lists. |
| `queue [--tier 1,2] [--spec confirmed\|unknown] [--user U] [--limit N] [--offset N]` | Ranked "to rate" queue for a user (default owner; tiers = `search.queue_default_tiers`): tier, deal, score, landed vs fair, why. |
| `profile` | The server's effective buyer profile: tiers, hard filters, options wanted, weights, users. |
| `show CAR [--user U]` | Full card (incl. `version`): family, good deal, specs + powertrain, seller + contacts, listings + price history, options, facts, verdicts, notes, photos, duplicates, timeline, chat. |
| `set CAR [spec/powertrain/seller flags] [--slug --summary --status --status-reason --seller-id --family NAME --red-flag-add/-rm… --question-add/-rm…] [--clear FIELD…] [--if-version N]` | PATCH: only given fields change; `--clear km` / `--clear powertrain.gearbox` sends null. `--family` overrides the derived model family. |
| `status CAR STATUS [--reason R] [--if-version N]` | `new to_contact contacted talking ready_to_visit visited closed dropped bought`. |
| `needs-owner CAR "reason"` · `needs-owner CAR --clear` | Flag for the owner's attention. |
| `verdict CAR up\|maybe\|down\|clear [--note N] [--user U]` | A user's verdict (default the token's user, else the owner; also 👍 🤔 👎). Viewer tokens may set only their own. |
| `deal CAR on\|off [--note N]` | Good-deal flag; unchanged = no event. |
| `opt CAR key=value[:source[:ref]]… [--source S] [--rm KEY…]` · `fact CAR …` | Options / facts with evidence. |
| `alias CAR ALIAS…` · `merge TARGET SOURCE…` · `split CAR --listing ID… [--move-messages] [--keep-photos]` | Identity. |
| `rm CAR --yes` | Hard delete with everything attached (without `--yes`: shows what would go, exit 2). Prefer `status CAR dropped`. |
| `dupes [--car CAR] [--status …]` · `dupe-reject ID…` | Duplicate proposals. |

### Chat, notes, timeline, photos

| command | what |
|---|---|
| `msg (--car CAR\|--url URL\|--to CONTACT) --channel CH --dir in\|out TEXT\|--text-file F\|-` | Log a message (`--at --sender --sender-kind --external-id --key --failed --error --delivery --attach… --allow-duplicate`). Near duplicates (same text within 5 min) return the existing row. |
| `msg rm ID… [--reason R]` · `msg restore ID…` · `msg dupes` · `msgs CAR` | Soft delete / undo / double-logged pairs / chat log. |
| `note CAR TEXT [--pin]` · `notes CAR` · `note-edit ID` · `note-rm ID…` | Notes. |
| `event CAR --type T --summary S [--data JSON] [--key K] [--at T] [--listing ID]` · `events CAR` | Timeline (idempotent on `--key`). |
| `photo add CAR FILE\|URL… [--listing ID --source --caption]` · `photo get ID [--size thumb\|medium\|full] -o F` · `photo ls\|edit\|rm` | Photos (idempotent per car by content). |

### Other

`seller show|set ID` · `families [--known]` · `stats [--user U]` · `activity [--since 24h]` · `health` · `config set|show` · `version` ·
`init` · `serve` · `backup DEST` · `healthcheck`.

## Development

```sh
go build ./... && go test -count=1 ./...
CARDB_SMOKE=1 go test ./internal/cli -run TestLiveSmoke -count=1 -v   # read-only checks of a running server
```

The e2e tests start the real server in-process over a temp dir and drive `cli.Run` exactly as an agent would. The live
smoke test defaults to `http://127.0.0.1:8484` (`CARDB_SMOKE_URL` / `CARDB_URL` override) and refuses a non-localhost
server unless `CARDB_E2E_ALLOW_REMOTE=1`, so a test run never writes to a live server.
