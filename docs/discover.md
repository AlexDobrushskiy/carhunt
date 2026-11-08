# discover

Finds listings on the enabled sites and stores them in cardb. Code: `carhunt/discover/`. Agent brief: `agents/roles/sweep/brief.md`. Site plugins (search/ad/live readers, `site.yaml`): [sites](sites.md).

## Flow
```
plan (enabled sites, read_after, --window)            one site at a time, lock `sweep`
└ per site: queries = search.models × site countries ∩ search.countries
  └ site.search(q) → Card
     ├ cursor.stop(card)? → end of query              (first organic in-filter card only)
     ├ scope.check(card, partial)  → drop + reason    (no load spent)
     ├ known in cardb? → unchanged (no write) | price moved → re-read, minimal upsert
     └ new: site.ad(url) (detail tiers) | card-only
        → normalize → heuristics → geocode → scope.check → quality → ingest
           ingest: upsert (no photos) → find_listing(url) → photo_add × N → phone check
  commit cursor per query only after a clean finish
Blocked → stop site, record signature · Gone → skip ad · budget/pace → stop site
```

## Commands
| command | what |
|---|---|
| `carhunt sweep [--sites a,b] [--window morning\|afternoon] [--dry-run] [--max N] [--json]` | the sweep. `--dry-run` reads sites, prints upsert bodies, writes nothing (no cardb, cursors, geocode calls). `--max N` = stop after N new listings. |
| `python -m carhunt.discover sweep …` | same, without the core dispatcher |

Exit: 0 all planned sites finished · 1 error · 3 a site ended `blocked`/`budget`/`pace` · 10 refused (PAUSE file, another sweep running).
Site states: `ok`, `blocked` (signature), `pace`, `budget`, `deferred` (read_after / window), `unsupported` (no reader), `max`, `error`.

## State (`$CARHUNT_HOME/discover/`)
| file | what |
|---|---|
| `cursors.json` | `{site: {"<country>\|<make>\|<model>\|<seller>": cursor}}` |
| `seen.json` | `<site>:<site_ref>` → the site's own ask at the last sweep (price-change detection) |
| `dispositions.jsonl` | every dropped ad + every cardb refusal / held price: site, url, reason |
| `runs/<ts>.json` | run report (per-site counters + every write) |
| `geocode.json` | place → lat/lon cache |

## Config
Values and defaults: [`config.example.yaml`](../config.example.yaml) `sites:`, `search:`, `discover:`. What discover does with each key:

| key | effect |
|---|---|
| `owner.home` | distance origin; home country decides home vs abroad rules |
| `sites.enabled` | sites the sweep runs (default: every plugin) |
| `search.countries` | site countries outside it get no query |
| `search.exclude_regions` / `exclude_places` | scope drop (ISO 3166-2 via `data/regions.yaml`, postcode first) |
| `search.price` | gross compare; `min_eur` is the one price floor (discover drops, cardb refuses) |
| `search.year_min`, `km_max`, `powertrain`, `max_distance_km`, `road_factor` | scope drop (distance = road km, else great-circle × `road_factor`) |
| `search.private_sellers_abroad` | `false` = dealer-only queries + scope drop abroad |
| `search.models` | make/model per query (+ `match:` regex override) and tier |
| `search.hard_filters` | cardb's grammar applied at ingest (`field` min/max, `fact(s)` min/max/words, `flag`); `mentions_country` is left to cardb's queue |
| `search.options_wanted` | keys drive the ask list (weights are cardb's) |
| `discover.windows`, `max_loads_per_site`, `max_pages`, `max_photos` | run plan + budget (`max_loads_per_site` = min() with site.yaml `pace.max_loads_per_run`) |
| `discover.detail_tiers` | tiers that get detail reads + gallery; others card-only (null = all) |
| `discover.cursor.<site>` | strategy override (see Rules) |
| `discover.price_sanity.max_eur`, `thin`, `heuristics`, `distance` | ×100 ceiling · thin-ad rule · plug-ins to load · geocoder/router (`none` = offline) |

Flags discover sets: `lease_transfer` (always dropped), `damaged`, `reseller`, `net_price`, `history_abroad`, `china_market_vin`, `net_price_unknown_vat`.

## Rules (why)
- **Serial, one sweep per machine.** Parallel workers on one IP got sites banned and killed each other's searches (2026-11-03).
- **Sends before reads.** Sites with `pace.read_after` are read only after it: discovery reads 403'd the IP used for seller messages (2026-11-05/06).
- **Budget ≤ 60 loads/site/run.** Home IP got a 403 on mobile.de after 41 sweep loads (2026-11-06).
- **Stop a site at the first block; gone ≠ blocked** (classification and why: [sites.md](sites.md#rules-why)).
- **Cursors only from organic, in-filter cards; checked before the cardb lookup; committed per query after a clean finish; merged, never replaced.** Promoted rows violate filters; a replaced cursor dict lost models with no eligible head.
- **Cursor strategy:** config `discover.cursor.<site>` > site.yaml `cursor.strategy` (`newest_id` \| `first_seen` \| `full`) > `first_seen`.
- **Newest-first cursors don't see price drops on older ads.** Price tracking of known listings = full-coverage sites + liveness/price checks (sites module).
- **Upsert without photos, then photos by resolved URL; later writes resolve by URL.** Dealer stock galleries auto-merged 4 cars, then a write hit the wrong car (2026-11-03).
- **No scoring, no merging here.** Ranking and dedupe are cardb's (one answer for web, CLI, agents); discover sends identity keys (VIN, plate, phone, `dealer_stock_ref`).
- **Prices gross.** Net asks + country VAT (`data/vat.yaml`); ES "precio al contado" beats a finance headline; IT "IVA esclusa" asks → gross. Net asks passed the price filter on day 1 (2026-11-03).
- **Price sanity before storing.** 10 prices were stored ×100 (2026-11-03). cardb refuses too (422 `{reason}`): `price_lease` → dropped (a rate/deposit, not a sale); `price_x100`/`price_range`/`price_net` → car stored **without price**, the ask in `price_note`, counted `price_held` + a disposition line. Agent: check the ad, then `cardb listing set ID --price N [--price-vat gross|net|margin]` (`--force` only after checking). Why: newest-first cursors move past the ad, so a dropped car is never seen again.
- **One bad ad never stops the run:** a 400/422 rejects that ad; cardb down / 5xx stops the sweep (exit 1).
- **Look up by URL, dedupe by `site_ref`.** cardb derives its own ref from the URL; standvirtual/olx.pt data ids (`Card.site_ref`) differ from that URL token, so cardb lookups go by URL and in-run dedupe + `seen.json` go by `site:site_ref`.
- **No `--if-version` here:** discover only upserts (fill-empty, never overwrite) and appends photos/facts; none of these take a version. Agents editing a car after a sweep use `cardb set … --if-version N` (docs/db.md).
- **Regions by postcode first.** A Tenerife car slipped through on the city name (2026-11-04); a street name never excludes.
- **Drive: site field → AWD words in the title → description words → plug-in variant rules; conflicts become a fact.** 49 % unknown until backfilled; a "Pro" was 4MOTION in its title (2026-11-03/04).
- **Power from title with checks:** skip charging kW ("DC 135 kW"); kW and hp must agree; a kW < 100 against an hp figure is a battery typo.
- **Phones E.164 digits per country** (`data/phone.yaml`). Subito numbers were stored without the 39 prefix (2026-11-04).
- **Unknown ≠ no.** Options without a cue stay absent; stated absence ("ohne Panoramadach") is `no`.
- **One thin rule for everyone** (`quality.py`): < 8 photos or < 3 of {owners, accident-free, service history, SoH, a wanted option}. Interior/odometer photos are always asked: discover can't see photos. Every agent had its own cut-off (2026-11-03).
- **Model match on make/model/title only, never the description** — dealer prose lists other models.

## Heuristics plug-ins
`carhunt/discover/heuristics/<name>.yaml`: `families`, `variants` (battery/power/drive per trim + year), `drive_rules`, `option_cues` (`kind: text` applied by discover; `kind: photo` for vet/agents, with validation counts), `pr_codes` (+ `decode_pr()`), `fallback_ask` (+ i18n) and `rules` with why. `vag_meb.yaml` (VW ID.4/ID.5, Škoda Enyaq, Audi Q4, Cupra Tavascan) is the worked example. New model group = new YAML, no code.

## Data files (`carhunt/discover/data/`)
`vat.yaml` · `regions.yaml` · `phone.yaml` · `keywords.yaml` (lease, damage, reseller, net wording, cash price, facts, fuel and drive vocab) · `options.yaml` (multi-language option cues, `present`/`absent`/`unless`). Languages: en de fr es it pt nl.

## Tests
`pytest carhunt/discover` — offline, synthetic. `test_e2e.py` runs a real `cardb serve` on temp data when `CARDB_BIN` (or `cardb` on PATH) is set: `--sites fake --max 5` → 5 cars, re-run → no writes. Cross-module round trip (sweep → vet ask → `carhunt asks close` → vet next ask): `carhunt/vet/tests/test_flow_e2e.py`.

## Gaps
- Detail reads for walled routes depend on the sites plugins + `carhunt.access.session` (browsers).
- Dedupe review (merge proofs, pHash) is an agent step (brief) on cardb's proposals.
