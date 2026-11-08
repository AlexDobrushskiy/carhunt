# cardb — design reference

Contract: `api/openapi.yaml` (wire types in `internal/api/types.go`). This file covers what the spec doesn't.
Operator guide (run modes, remote access, backups, backfills): [`docs/db.md`](../docs/db.md).

## Binary
One Go binary `cardb` (`cmd/cardb`), pure Go (`modernc.org/sqlite`, CGO off, `-tags nodynamic` for static builds):
- `cardb serve` — HTTP server. Env: `CARDB_DATA_DIR` (default `./data`), `CARDB_LISTEN` (default `127.0.0.1:8484`),
  `CARDB_TOKENS` (`name:token,…`) or `CARDB_TOKENS_FILE` (one entry per line; `cardb init` writes hashed
  `name:sha256:<hex>` lines), `CARHUNT_CONFIG` / `CARHUNT_HOME` → buyer profile (missing file = neutral profile).
- `cardb init` — data dir + tokens + client config; tokens stored through the secrets lookup (below).
- `cardb backup <dest.sqlite3>` — `VACUUM INTO` snapshot of `$CARDB_DATA_DIR/cardb.sqlite3` (no API; run where the data dir is).
- `cardb healthcheck` — GET `/healthz` on `$CARDB_LISTEN` (Docker HEALTHCHECK).
- every other subcommand is an API client: `--server/--token/--author` > env `CARDB_URL`/`CARDB_TOKEN`/`CARDB_AUTHOR`
  > `~/.config/cardb/config.json` (`$CARDB_CONFIG`). Author also falls back to `$AGTERM_SESSION_ID`. `--json` everywhere.

## Layout
`internal/api` wire types · `internal/profile` config loader (owner/search/cardb sections) · `internal/store` SQLite schema,
queries, dedupe, merge/split, ranking · `internal/server` HTTP handlers (Go 1.22 `net/http` patterns, no router lib) ·
`internal/imaging` decode, pHash, thumbnails · `internal/client` typed HTTP client · `internal/cli` subcommands.

## Storage
- `$CARDB_DATA_DIR/cardb.sqlite3`, WAL, `foreign_keys=ON`, `busy_timeout=5000`, one writer connection. WHY: one data dir =
  one backup path (snapshot + `photos/`); Postgres would need its own backed-up instance for no gain at this scale.
- Migrations: `PRAGMA user_version` + ordered list in `internal/store/schema.go` (SQL or Go func per step). An older
  evdb database migrates on first start (legacy columns renamed); see docs/db.md "Migrating an evdb database".
- Timestamps stored as Unix epoch REAL seconds; the API emits RFC 3339 UTC.
- Photos on local disk: `$CARDB_DATA_DIR/photos/<sha256[:2]>/<sha256>.jpg` (re-encoded JPEG q85, max 2000 px); derived
  `…-thumb.jpg` (400 px) / `…-medium.jpg` (1000 px), generated lazily. Responses: `Cache-Control: private, max-age=31536000, immutable`, ETag = sha.
- Backup = `cardb backup` snapshot + a copy of `photos/` (restic or any file backup).

## Tables (sketch)
- `cars`: id, slug UNIQUE NULL, spec columns (`CarSpecs`, incl. `distance_km`), powertrain columns (`Powertrain`: fuel,
  battery net/gross kWh, engine_cc, gearbox, WLTP range/consumption, CO2), seller_id, summary, status, status_reason,
  status_changed_at, needs_owner, needs_owner_reason, red_flags JSON, open_questions JSON, merged_into NULL (tombstone),
  model_family_override, good_deal/_note/_by/_at, **version** (incremented on every car write), created_at, updated_at.
- `car_aliases`: alias PK (case-insensitive), car_id. The slug is also an alias. `{car}` lookup: numeric → id (follow merged_into); else alias.
- `sellers`: id, name, type, company, city, note. `seller_contacts`: seller_id, kind, value, note, shared. An own contact
  (shared = 0) is unique per kind+value; a shared one (portal call centre, group switchboard) sits on every seller whose ad
  prints it. Upsert resolves a seller by an own contact only when the names don't conflict; a contact seen with a
  differently named seller becomes shared on both. Shared contacts never pick a seller, route a message (`--to`) or count
  as duplicate evidence. WHY: shared dealer numbers merged unrelated sellers (6 contact-owner conflicts, EV run).
  Phones: digits only with country code; a number without one gets the calling code of `owner.home.country`. Emails lowercased.
- `listings`: id, car_id, url (normalized) UNIQUE, site, site_ref, title, status, price, price_note, price_vat,
  price_flags, seller_id, first/last_seen_at, removed_at, raw JSON. `price_points`: listing_id, price, at, note.
- `options`: car_id, key, value, source, source_ref, note, author, updated_at; PK(car_id,key). `facts`: same shape, free-text value.
- `photos`: id, car_id, listing_id, sha256, phash (64-bit), width, height, position, cover, caption, source, source_ref; UNIQUE(car_id, sha256).
- `events`: id, car_id, listing_id, type, at, author, summary, data JSON, dedupe_key UNIQUE NULL.
- `messages`: id, car_id, seller_id, channel, direction, at, sender_kind, sender, counterpart, text, attachments JSON,
  delivery, error, external_id, dedupe_key, deleted_at/by/reason; UNIQUE(channel, external_id), UNIQUE(dedupe_key).
- `notes`: id, car_id, author, author_kind, text, pinned, created_at, updated_at.
- `users`: name PK, role owner|viewer (owner from `owner.name`, viewers from `cardb.users`).
  <!-- TODO(lead): confirm users table shape after merging mod/db-users -->
- `verdicts`: (car_id, user) PK, value, note, author, updated_at; every change also writes a `verdict` event.
- `duplicates`: id, car_a < car_b, score, reasons JSON, status proposed|rejected|merged; UNIQUE(car_a,car_b). Rejected pairs are never re-proposed.

## Write rules (each with its why)
- **Every write is idempotent.** Upsert by normalized URL / site ad id; `msg` by `external_id` / `dedupe_key` / derived
  sha1(channel|dir|counterpart|text|minute); `event --key` stored once; photos by sha256 per car. Agents re-run blindly;
  a replay must make 0 writes.
- **Upsert fills only empty car fields unless `overwrite`; `status` applies only on car creation.** Several agents describe
  the same car; a later sloppy ad must not clobber a confirmed value.
- **Re-upserting a removed/sold ad relists it only if `seen_at` is later than the removal.** Replaying old sightings without
  `seen_at` resurrected dead ads.
- **Message near-duplicate guard:** same car+channel+direction+normalized text (+ attachment kinds, agreeing counterpart)
  within 5 min under another key returns the existing row (`matched_by: near_duplicate`). Not when both carry different
  external ids, failed ≠ failed, or two different caller keys of one family (prefix before the first non-letter).
  `allow_duplicate` logs a deliberate repeat. WHY: a history import and a catch-up script logged 16 first contacts twice.
- **Message delete is soft** (keys kept, `message_deleted` event, `msg restore`). A logger re-posting can't resurrect it.
- **Log incoming messages verbatim, in the original language, when read.** Paraphrases can't be re-checked; translations go in a note.
- **Never overwrite a strong evidence source with a weak one** (photo/agent_inference never replaces seller_said,
  vin_pr_code, inspection, owner). On conflict keep the value and add a `*_conflict` fact. When in doubt write `unknown`:
  a wrong `no` hides a good car.
- **Unknown ≠ no everywhere** (filters `yes_or_unknown`, `?` icons, `? km` in the queue). Missing data must not drop a car.
- **Price sanity on write** (upsert, PATCH listing): ×100 (cents), lease/monthly rate, net-of-VAT, out-of-range → 422
  `{reason}` unless `force`; forced prices keep `price_flags` + a `price_sanity_override` event. WHY: 10 prices were
  stored ×100 in the EV run. <!-- TODO(lead): exact thresholds from mod/db-schema -->
- **Optimistic locking:** `If-Match: "<version>"` (or body `version`) on PATCH/status → 412 + current car when stale;
  no If-Match = last writer wins. `red_flags_add/_remove`, `open_questions_add/_remove` are atomic item ops. WHY: list
  PATCH replaced the whole list and concurrent agents dropped each other's items.
- **API changes stay additive** while agents write all day; avoid long migration locks.

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
  score 0.9). WHY: dealer stock photos once auto-merged 4 different cars into one (one car collected 29 listings; 47 repaired).
- **Never the same car** unless VIN/plate say so: different VINs, different make, different model family (first word of the model).
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
- `distance_km` = stored value, else a great-circle estimate from the car's lat/lon to `owner.home` × `search.road_factor`
  (`distance_source` stored|estimate). `market` = `home` when country == `owner.home.country`, else `abroad`.
  <!-- TODO(lead): confirm road_factor default + where car lat/lon come from (mod/db-rank) -->
- model_family = override, else derived at read time from make/model/variant (`internal/store/family.go` built-in table
  + `search.families` + `search.models` from config). Never stored, so a rule change is its own backfill. Ambiguous models
  stay unmapped (`none`) on purpose.
- verdict = the owner's (or `?user=`); `verdicts` = every user's. deal_rank = the `deal_rank` fact (`T<tier>-<n>`).

## Ranking (GET /queue, `cardb queue`)
One pure function in `internal/store` (inputs: car summaries + facts + profile + now), shared by API, CLI and web.
Nothing is stored. WHY: one answer everywhere; a recomputation over the live EV queue found 0 order violations.
Every constant below is a `search.ranking.*` / `search.*` config key; the values shown are the defaults.
<!-- TODO(lead): align key names with mod/db-rank -->

1. **Eligible** = no verdict from the user; status not closed/dropped/bought; ≥ 1 live listing; every hard filter of the
   profile (`year_min`, `price.max_eur`, `km_max`, `countries`, `exclude_regions`/`exclude_places`, `powertrain`,
   `hard_filters` rules). A missing value passes and shows as `? year` etc. in `why`.
2. **Tier** = first `search.models` entry whose family matches and whose `when` holds (power band, drive, variant tokens,
   year, battery, fuel), else `default_tier`. Power known → power decides; unknown → `variant_any` tokens (trim marker).
3. **Peer group** (the car is never its own peer; pool = live, priced, in scope, no VAT reserve, not closed/dropped;
   outliers outside 0.67×–1.65× of a band median with n ≥ 8 dropped). Ladder: family+trim+year+km band (n ≥ 8) →
   family+trim+year (6, adjusted) → family+trim (3, adjusted) → family (3, adjusted) → none (value 50, thin-sample risk).
   Trim = power band (hp rounded to 25) + AWD/2WD. Adjust: `(car.year − peer.year)·2000 + (peer.km − car.km)·0.06`.
4. **Fair** = median of per-country medians (one vote per country), rounded to 50; `fair_landed` the same over landed costs.
5. **Landed** = price + trip + registration + VAT reserve. Trip by distance (home: 50/100/200 by ≤100/≤500/more km;
   abroad: travel + plates/insurance + fuel/energy + tolls + nights + food); registration 65 home / 250 import; VAT reserve
   (abroad, "new means of transport": km ≤ 6000 or registered < 6 months) = destination VAT % of price + risk.
   Missing distance → per-country default + risk 0.5.
6. **value** = 50 + 2·clamp(gap_pct, −15, 20) (20…90), gap_pct = (fair_landed − landed)/fair_landed·100.
7. **fit** = base_fit (per model, default 0.40) + w.fit·Σ terms: wanted options (yes +, no −; `options_wanted` weight ×
   0.03), penalties, seller private +0.06 / reseller −0.12, home market +0.04, age, km, history facts.
8. **risk** = unknown must-have/wanted options, no VIN, no service history/owners/accidents fact, no powertrain-health
   fact (e.g. battery SoH for BEV/PHEV), estimated distance, reseller, VAT reserve, thin or wide peer group, model risk,
   each red flag, a forced price. Top contributors → `risk_reasons`.
9. **score** = w.value·value·fit − w.risk·risk (null without a price).
10. **Order**: tier asc; good_deal first; deal_rank (parsed, unparseable, missing); score desc; landed asc (missing last);
    created_at desc; id desc.

`spec=confirmed|unknown` filters on the profile's `must_have` options before counting. `why` (≤ 160 chars): good-deal
note, else known wanted options, the gap, then unknowns.

## Auth and users
- Bearer token in the `Authorization` header only (never in a URL), compared in constant time. Tokens are named; the name
  is the default author. Body `author` > `X-Author` > token name.
- `author_kind` = `owner` when author == `owner.name`, `viewer` for a configured viewer, `import` for imports, else `agent`.
- A token named like a viewer is read-only except for that viewer's own verdict (403 otherwise).
- The web UI never sees a token: `/ui/*` is an allowlist proxy that sends the signed-in user as author; photos are proxied.
- `/healthz`, `/api/v1/health`, `/api/v1/openapi.yaml` need no token.
