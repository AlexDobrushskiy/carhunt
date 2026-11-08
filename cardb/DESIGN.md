# cardb — design reference

Contract: `api/openapi.yaml` (wire types in `internal/api/types.go`). This file covers what the spec doesn't.
Operator guide (run modes, config keys, remote access, backups, backfills): [`docs/db.md`](../docs/db.md).

## Binary
One Go binary `cardb` (`cmd/cardb`), pure Go (`modernc.org/sqlite`, CGO off, `-tags nodynamic` for static builds):
- `cardb serve` — HTTP server. `CARDB_LISTEN` (default `127.0.0.1:8484`); data dir `--data` > `CARDB_DATA_DIR` >
  config `cardb.data_dir` (relative or `$CARHUNT_HOME/…` resolved against the carhunt home) > `$CARHUNT_HOME/cardb`;
  tokens `CARDB_TOKENS` / `CARDB_TOKENS_FILE`, else `<data dir>/tokens`;
  profile `--config` > `CARHUNT_CONFIG` > `$CARHUNT_HOME/config.yaml` (missing file = neutral profile, invalid = refuse to start).
- `cardb init [--home H] [--backend keychain|file|op] [--rotate]` — data dir (0700), tokens, secrets; idempotent (see docs/db.md).
- `cardb backup <dest.sqlite3>` — `VACUUM INTO` snapshot (no API; run where the data dir is).
- `cardb healthcheck` — GET `/healthz` on `$CARDB_LISTEN` (Docker HEALTHCHECK).
- every other subcommand is an API client (`--json` everywhere):
  URL `--server` > `CARDB_URL` > `~/.config/cardb/config.json` > config `cardb.url` > `http://127.0.0.1:8484`;
  token `--token` > `CARDB_TOKEN` > secret `cardb_token` (or `cardb.token: secret:<name>`) via env `CARHUNT_SECRET_<NAME>`
  then the secrets backend; author `--author` > `CARDB_AUTHOR` > client config `author` > (server) token name.
  The client config file never holds a token.

## Layout
`internal/api` wire types + enums (fuel/gearbox synonyms) · `internal/profile` config loader, defaults, validation ·
`internal/geo` generic data (regions, country names, dialing plans, centroids, VAT rates) · `internal/store` SQLite
schema, queries, dedupe, merge/split, price sanity, versions, ranking (`rank.go`, `queue.go`), model families
(`families.yaml`) · `internal/server` HTTP (Go 1.22 `net/http` patterns) · `internal/setup` + `internal/secrets`
(`cardb init`, secrets lookup shared with the Python core) · `internal/imaging` decode, pHash, thumbnails ·
`internal/client` typed HTTP client · `internal/cli` subcommands.

## Storage
- `<data dir>/cardb.sqlite3`, WAL, `foreign_keys=ON`, `busy_timeout=5000`, one writer connection. WHY: one data dir =
  one backup path (snapshot + `photos/`); Postgres would need its own backed-up instance for no gain at this scale.
- Migrations: `PRAGMA user_version` + ordered list in `internal/store/schema.go` (SQL or Go func per step).
  5 legacy column renames · 6 powertrain + version + price VAT/flags · 7 users + per-user verdicts · 8 car lat/lon.
- Timestamps stored as Unix epoch REAL seconds; the API emits RFC 3339 UTC.
- Photos on local disk: `<data dir>/photos/<sha256[:2]>/<sha256>.jpg` (re-encoded JPEG q85, max 2000 px); derived
  `…-thumb.jpg` (400 px) / `…-medium.jpg` (1000 px), generated lazily. Responses: `Cache-Control: private, max-age=31536000, immutable`, ETag = sha.

## Tables (sketch)
- `cars`: id, slug UNIQUE NULL, spec columns (`CarSpecs` incl. `distance_km`, `lat`/`lon`), powertrain columns (fuel,
  battery net/gross kWh, engine_cc, gearbox, wltp_range_km, wltp_consumption, co2_g_km), seller_id, summary, status,
  status_reason, status_changed_at, needs_owner, needs_owner_reason, red_flags JSON, open_questions JSON, merged_into
  NULL (tombstone), model_family_override, good_deal/_note/_by/_at, **version**, created_at, updated_at.
- `car_aliases`: alias PK (case-insensitive), car_id. The slug is also an alias. `{car}` lookup: numeric → id (follow merged_into); else alias.
- `sellers` + `seller_contacts` (kind, value, note, shared). An own contact (shared = 0) is unique per kind+value; a
  shared one (portal call centre, group switchboard) sits on every seller whose ad prints it. Upsert resolves a seller by
  an own contact only when the names don't conflict; a contact seen with a differently named seller becomes shared on
  both. Shared contacts never pick a seller, route a message (`--to`) or count as duplicate evidence. WHY: shared dealer
  numbers would merge unrelated sellers. Phones: digits with country code; a
  national-format number gets the calling code of `owner.home.country` (its dialing plan). Emails lowercased.
- `listings`: id, car_id, url (normalized) UNIQUE, site, site_ref, title, status, price, price_note, price_vat
  (gross|net|margin|unknown), price_flags JSON, seller_id, first/last_seen_at, removed_at, raw JSON. `price_points`: listing_id, price, at, note.
- `options`: car_id, key, value, source, source_ref, note, author, updated_at; PK(car_id,key). `facts`: same shape, free-text value.
- `photos`: id, car_id, listing_id, sha256, phash (64-bit), width, height, position, cover, caption, source, source_ref; UNIQUE(car_id, sha256).
- `events`: id, car_id, listing_id, type, at, author, summary, data JSON, dedupe_key UNIQUE NULL.
- `messages`: id, car_id, seller_id, channel, direction, at, sender_kind, sender, counterpart, text, attachments JSON,
  delivery, error, external_id, dedupe_key, deleted_at/by/reason; UNIQUE(channel, external_id), UNIQUE(dedupe_key).
- `notes`: id, car_id, author, author_kind, text, pinned, created_at, updated_at.
- `users`: name, role owner|viewer — synced from the profile on every start (owner = `owner.name`, viewers =
  `cardb.users`). The owner is *the* row with role `owner`, so renaming `owner.name` keeps the owner's verdicts.
- `verdicts`: (car_id, user) PK, value, note, author, updated_at; every change also writes a `verdict` event.
- `duplicates`: id, car_a < car_b, score, reasons JSON, status proposed|rejected|merged; UNIQUE(car_a,car_b). Rejected pairs are never re-proposed.

## Write rules (each with its why)
- **Every write is idempotent.** Upsert by normalized URL / site ad id; `msg` by `external_id` / `dedupe_key` / derived
  sha1(channel|dir|counterpart|text|minute); `event --key` stored once; photos by sha256 per car. Agents re-run blindly;
  a replay must make 0 writes.
- **Upsert fills only empty car fields unless `overwrite`; `status` applies only on car creation.** Several agents describe
  the same car; a later sloppy ad must not clobber a confirmed value. Powertrain fills field by field the same way.
- **Re-upserting a removed/sold ad relists it only if `seen_at` is later than the removal.** Replaying old sightings without
  `seen_at` would resurrect dead ads.
- **Message near-duplicate guard:** same car+channel+direction+normalized text (+ attachment kinds, agreeing counterpart)
  within 5 min under another key returns the existing row (`matched_by: near_duplicate`). Not when both carry different
  external ids, failed ≠ failed, or two different caller keys of one family (prefix before the first non-letter).
  `allow_duplicate` logs a deliberate repeat. WHY: an import and a catch-up logger can both log the same message.
- **Message delete is soft** (keys kept, `message_deleted` event, `msg restore`). A logger re-posting can't resurrect it.
- **Log incoming messages verbatim, in the original language, when read.** Paraphrases can't be re-checked; translations go in a note.
- **Never overwrite a strong evidence source with a weak one** (photo/agent_inference never replaces seller_said,
  vin_pr_code, inspection, owner). On conflict keep the value and add a `*_conflict` fact. When in doubt write `unknown`:
  a wrong `no` hides a good car.
- **Unknown ≠ no everywhere** (filters `yes_or_unknown`, `?` icons, `? km` in the queue). Missing data must not drop a car.
- **Powertrain input:** nested `powertrain{…}` is the contract; flat `battery_net_kwh`/`battery_gross_kwh` on upsert and
  POST /cars are still folded in (422 when they disagree with the nested value). WHY: flat-field clients must not lose the value
  silently. Fuel/gearbox take ad words in PT/ES/FR/DE/IT/NL/EN (`elétrico`→bev, `plug-in`→phev, `gasóleo`→diesel,
  `GPL`→lpg, `DSG`/`automático`→automatic, …); an unrecognised word is 400.
- **API changes stay additive** while agents write all day; avoid long migration locks.

## Price sanity (upsert, PATCH /listings/{id})
Checked only when the price changes (re-sending the stored price is not re-checked, so replays stay idempotent).
Failures, most severe first; the first one is the 422 `{error, reason, price, expected}`:

| reason | rule (bounds from `search.price`) |
|---|---|
| `price_range` | price ≤ 0, or > `cap_eur` (default 2 000 000) and ÷100 is not plausible |
| `price_x100` | > `cap_eur` while ÷100 lies in `min_eur`…`cap_eur`; or > 8× the family median (≥ 3 live unflagged cars in the family); or, without a median, > 8× `max_eur` |
| `price_lease` | < `min_eur` (default 1500: a monthly rate or deposit); or "low" (< median/4, or < 10× `min_eur` without a median) with monthly/lease wording (`/mês`, `per month`, `monatlich`, `leasing`, `renting`, `LOA`, …) in title or price note |
| `price_net` | `price_vat: net`; or net wording (`excl. VAT`, `+IVA`, `zzgl. MwSt`, `netto`, `HT`, `sin IVA`, …) without gross wording (`brutto`, `incl. VAT`, `TTC`, `IVA dedutível`, …) unless `price_vat` is gross/margin |

`force: true` stores the price anyway: `price_flags` on the listing (and `CarSummary.price_flags`), a
`price_sanity_override` event; the ranking drops the car from the comparable pool and adds `risk.price_forced`.
WHY: ×100 prices sort as bargains; lease and net prices skew fair prices.

## Versions (optimistic locking)
- `cars.version` is an **opaque** counter: it rises (by ≥ 1) on any write that changes the car row or anything shown on
  the car — listings, price points, options, facts, photos, events, messages, notes, verdicts, aliases, duplicate
  proposals, its seller. Clients compare it, never compute it. Sightings that only move `last_seen_at`/`raw` don't count.
- Implemented as SQLite triggers, dropped before migrations and rebuilt from the live schema on every open, so new
  tables with a `car_id` and new columns are covered without code changes.
- `GET /cars/{car}` (and PATCH/status responses) send `ETag: "<version>"`; GET /cars rows and queue items carry `version`.
- `PATCH /cars/{car}` / `POST …/status` with `If-Match: "<n>"` or body `version` → 412 `{error, version, car}` when
  stale; without it last writer wins. `red_flags_add/_remove`, `open_questions_add/_remove`: exact text, atomic,
  idempotent (422 when combined with a full replace of the same list). WHY: list PATCH replaced the whole list and
  concurrent agents dropped each other's items; a status lagged its chat.

## URL normalization
Lowercase scheme+host, strip `www.`/`m.` for matching, drop fragment and tracking params (`utm_*`, `fbclid`, `gclid`,
`ref`, `src`…), drop trailing `/`. `site` + `site_ref` per site (`internal/store/normalize.go`): standvirtual / olx.pt
`ID[0-9A-Za-z]+`; custojusto trailing number; mobile.de `id=`; autoscout24 trailing UUID; lacentrale
`/auto-occasion-annonce-(\d+)`; leboncoin `/(\d+)`; coches.net trailing number. Same site+site_ref = same listing even
if the slug differs. A site without a rule falls back to the full URL and loses cross-URL dedupe: add a rule with the site.

## Dedupe
Runs when upsert creates a car and whenever VIN/plate/seller contacts/photos change.
- **Certain → auto-link/merge** (`merge` event with reason): same VIN (uppercase, 17 chars); same plate (alnum uppercase);
  same private-seller phone AND same make+model. WHY: dealers share phones across their stock.
- **Photos** (pHash, Hamming ≤ 6) count only when distinctive: a picture on ≥ 3 distinct cars is a banner/stock image and
  is ignored. ≥ 2 distinctive matches covering ≥ ½ of the smaller set attach a NEW listing (`linked_by: photos`) only if
  make and model family agree, no known spec contradicts (year, km apart > max(5000, 15 %), plate, phones with none shared),
  the car is not closed/dropped/bought and no second car matches. Two existing cars are never merged on photos (proposal,
  score 0.9). WHY: dealer stock photos would auto-merge different cars into one.
- **Never the same car** unless VIN/plate say so: different VINs, different make, different model family (first word of
  the model), two different known fuels (`mhev` stays compatible with petrol/diesel/hev). WHY: a BEV and the petrol
  version of the same model share photos and model names.
- **Likely → proposal** (score 0..1 + reasons): 1 distinctive photo match; same phone any seller type + same model; same
  make+model+year + km within ±5 % or ±3000 + (same city or colour); same make+model+reg_date+colour. Contradictions listed as "but …".
- Agents: upsert the car without photos, then `photo add --listing`, and resolve later writes by `find-listing URL`, never
  by a stored car id — a merge can change the id under you.

## Merge / split
- Merge sources into target: move listings, messages, notes, photos (dedupe by sha), events, aliases; options/facts where
  the target lacks the key; each user's verdict where the target has none from that user; model_family_override and the
  good-deal flag if the target has none; spec/powertrain columns filled where the target is NULL; seller from target unless
  NULL; status = the more advanced unless one is closed/dropped/bought (keep target's); source.merged_into = target.
- Split: new car with copied specs + seller + model_family_override (never the good-deal flag); move the given listings and
  their photos; with `move_messages` also messages whose counterpart matches the moved listings' seller contacts.

## Derived fields (CarSummary)
- price = min over live listings, else the most recent listing price. price_drop = first price point − current.
- last_activity_at = max(updated_at, latest event, message, note, listing last_seen).
- `market` = `home` when country == `owner.home.country`, else `abroad`. `distance_km` = stored value
  (`distance_source: stored`), else great-circle(car lat/lon → `owner.home`) × `search.road_factor` (default 1.3,
  `estimate`); none without both points.
- model_family = override, else derived at read time from make/model/variant: built-in `internal/store/families.yaml`
  + `search.families` (same make + name overrides, else checked first) + an automatic rule for each `search.models`
  entry no rule matches. Never stored, so a rule change is its own backfill. Ambiguous models stay unmapped (`none`).
- verdict = the requested user's (default owner); `verdicts` = every user's. deal_rank = the `deal_rank` fact (`T<tier>-<n>`).
- tier, score, landed, fair_* come from the ranking below (GET /cars `sort=score` uses it too).

## Ranking (GET /queue, `cardb queue`, GET /cars?sort=score)
One pure function of (cars, facts, profile, now) in `internal/store/rank.go`, shared by API, CLI and web; nothing is
stored. WHY: one answer everywhere. Every number below
is a `search.ranking.*` default (docs/db.md has the full key list).

1. **Eligible** (per user, default owner): no verdict from that user; status not closed/dropped/bought; ≥ 1 live listing;
   in scope — `year_min`, `price.max_eur` (the only price filter; `min_eur`/`cap_eur` are write-time sanity only),
   `km_max`, `countries`, `exclude_regions` (ISO 3166-2 via place names), `exclude_places`, `powertrain` fuels, then
   each `hard_filters` rule. A missing value passes and shows as `? year` etc.
2. **Tier** = first `search.models` entry whose family (or make, when `model` is empty) matches and whose `when` holds,
   else `default_tier` (default: highest model tier + 1). `when` ranges (`power_hp`, `battery_net_kwh`): a known value
   must be in range; unknown → `variant_any` (the trim marker) decides when set, else passes. `variant_none` always
   applies; `quattro`/`4motion`/… count as awd. Power is read from `power_kw` or the ad text (`210 kW`, `286 CV`).
3. **Landed cost** = price + trip + registration (+ VAT reserve). Distance = car distance, else
   `default_distance_km[country]` → great-circle(home, country centroid) × road_factor → `default_distance_km.other` →
   2500 abroad (risk `distance_unknown`). Home: `home_trip` steps (≤100 km 50, ≤500 km 100, else 200) + 65 registration.
   Abroad: travel step (≤700 km 50, else 100) + 250 fixed (export plates + insurance) + (0.10 + 0.035)·km + 100 per
   night (none ≤ 700 km, else ⌈km/1300⌉ ≤ 2) + food step (≤700 km 30, else 60) + 250 registration. VAT reserve (abroad,
   "new means of transport": km ≤ 6000 or registered < 6 months ago) = home VAT rate % of price, + risk.
4. **Comparable pool**: live, priced, price not forced, in scope (price cap aside), no VAT reserve, mapped family, not
   closed/dropped; within a family+trim band of ≥ 8 drop asks outside 0.67–1.65 × the band median.
5. **Peer ladder** (the car is never its own peer). trim = power rounded to 25 hp + awd/2wd; km bands < 15k, < 30k, more.
   | step | peers | min n | adjusted |
   |---|---|---|---|
   | 1 | family + trim + year + km band | 8 | no |
   | 2 | family + trim + year | 6 | yes |
   | 3 | family + trim | 3 | yes |
   | 4 | family (all trims) | 3 | yes |
   Adjusted peer price += (car.year − peer.year)·2000 + (peer.km − car.km)·0.06.
6. **Fair** = median of per-country medians (each country one vote), rounded to 50; `fair_landed` the same over
   landed costs; IQR of peers' landed for the spread risk.
7. **value** = 50 + 2·clamp(gap, −15, 20) ∈ 20…90, gap % = (fair_landed − landed)/fair_landed·100; 50 without peers.
8. **fit** = base_fit (model entry, else 0.40) + w.fit·Σ: options_wanted yes +w·0.03 / no −w·0.03; each penalty hit
   −weight·0.03; private seller +0.06, reseller −0.12; home market +0.04; 0.005·max(0, 8 − age years);
   0.03·(1 − km/km_ref) (km_ref = km_max, else 50 000); +0.015 each for one owner, service history, accident-free. 3 decimals.
9. **risk** (points): each unknown must_have / top-4 wanted option 0.8; no VIN 0.8; no service history 0.8; no owners
   0.5; no accident fact 0.8; no powertrain-health fact (`health_facts[fuel]`, default battery_soh… for bev/phev) 1;
   distance unknown 0.5; reseller 4; VAT reserve 4; peers < 8: 3; spread (IQR/fair_landed) > 0.15: 3; model `risk`;
   each red flag 3; forced price 0.5. Top 5 → `risk_reasons`.
10. **score** = w.value·value·fit − w.risk·risk (2 decimals; null without a price).
11. **Order**: tier asc; good_deal first; deal_rank (parsed `T<tier>-<n>`, then unparseable, then missing); score desc
    (missing last); landed asc (missing last); created_at desc; id desc.

`spec=confirmed|unknown` filters on `must_have` before counting. `trim_score` = numeric `trim_score` fact, else
Σ options_wanted (yes +w, no −w) − penalties. `why` (≤ 160 chars): good-deal note, else known wanted options, penalties
hit, the gap vs peers, then unknown must-haves and missing core fields.

## Auth, users, verdicts
- Bearer token in the `Authorization` header only (never in a URL), compared in constant time against
  `name:sha256:<hex>` entries (legacy plain `name:token` still read). The token name is the default author.
  Body `author` > `X-Author` > token name.
- `author_kind` from the users table: `owner` · `viewer` · `import` (author starts with `import`) · `agent`.
- A viewer's token is read-only except that viewer's own verdict (403 otherwise) and always writes as the viewer.
- Verdict user = body `user` > `?user=` > the token's user > the owner (unknown user 422). GET /cars, /cars/{car},
  /stats, /queue take `?user=` (unknown 400) and always return `verdicts` for every user.
- **Legacy owner rewrite** (each start, idempotent): option/fact `source`, message `sender_kind` and note `author_kind`
  equal to lower(`owner.name`) become `owner`; skipped when the name is itself a vocabulary word. WHY: older data
  stored the owner's first name as an identity.
- The web UI holds one token per user (`cardb_web_tokens`), so its writes carry that user's name and rights; the
  browser never sees a token. `/healthz`, `/api/v1/health`, `/api/v1/openapi.yaml` need no token.
