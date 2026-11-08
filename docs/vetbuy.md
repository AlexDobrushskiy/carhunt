# vetbuy module

Facts about one car → evidence pack → visit-ready gate → buy → import. Code and content: `carhunt/vet/`, `knowledge/`, `skills/carhunt-vet/`, `agents/roles/{vet,buy}/`.

## Commands
| command | what | exit |
|---|---|---|
| `carhunt vin decode VIN [--reg YYYY-MM] [--vpic] [--json]` | WMI/manufacturer, country/region, model year, plant code, check digit, market flags; `--vpic` adds NHTSA vPIC (network) | 0 · 2 red flag |
| `carhunt vin check-digit VIN` | expected position-9 digit | 0 match · 3 mismatch · 1 bad input |
| `carhunt vin rdw PLATE [--json]` | NL RDW open data (`m9d7-ebf2` + recalls `t49b-isb7`): import date, odometer verdict, open recall, APK, export flag; prints the `cardb fact` line | 0 · 3 not found |
| `carhunt vin prcodes CODES… [--brand vag] [--json]` | sticker codes → options, unknown codes, `cardb opt` args (source `vin_pr_code`) | 0 |
| `carhunt evidence CAR [--write-asks] [--max-asks N] [--json]` | evidence-pack state from cardb; with `--write-asks` posts the next `ask` event(s) | 0 visit-ready · 4 not · 1 no config / cardb error |
| `python -m carhunt.vet.md2html F.md [-o F.html] [--cards]` | phone-friendly HTML report (light/dark, V/A/I + risk pills) | 0 |

Doctor (`carhunt doctor`): bundled WMI + PR-code tables load, `markdown` present, `knowledge/import/<dest>-registration.md` exists for `vet.destination_country`.

## Evidence pack
Items in ask order (one open ask at a time by default): `registration_doc`, `vin`, `vin_check` (vet's own checks, no ask), `service_history`, `battery_health` (fact `battery_soh`; also read: `soh`, `battery_health`, `battery_report`, `battery_cert`, `battery_test` = cardb `ranking.health_facts`; BEV/PHEV or unknown powertrain), `recall_status`, `odometer_photo`, `charging_inlet` (BEV/PHEV with China/US VIN flag or fact `import=yes…`), `warranty`, `accidents`; optional `tyres`, `video_walkaround`, `history_report`.
- **Visit-ready** = all required items have a value, no `refused…` value on a required item, no red VIN flag, no `*_conflict` fact. Why: a viewing should end in a purchase; every surprise is found before the trip.
- **Ask events:** `type=ask`, `summary` = English question (outreach localises), `data {topic, fact, why, item}`, `dedupe_key ask:<car>:<topic>:<n>`. Outreach closes with `carhunt asks close` → `ask_answered` `data {ask_event, topic}` + the answer into fact `data.fact` (when empty); the next run then asks the next item. A topic is open while it has more `ask` than `ask_answered` events. Why one at a time: short asks get answers, long question lists don't.
- Values `unknown|pending|asked|missing|n/a|?` count as missing; `refused…` = refusal (red flag, never re-asked; owner decides).

## Rules (why)
- Vet never messages sellers; it writes `ask` events (one channel owner per seller; avoids duplicate/clashing messages).
- Control lookup before trusting any checker: some answer "not affected" or invent records for a fake VIN.
- Check digit is mandatory only for North-American and Chinese VINs; on EU VINs a mismatch is no signal (most EU makers don't compute it).
- China-market JV WMI (FAW-VW, SAIC-VW, BMW Brilliance…) = red: GB/T charging, no EU warranty (often sold as "importado"). China-built EU-export models (Tesla Shanghai, Polestar, MG…) = info only; confirm the inlet.
- Model year > first-reg + 1 or < first-reg − 2 → warn (storage, re-registered import, or a wrong VIN).
- PR-code "none:" rows map to `no`; a `yes` from a sibling code wins. Source `vin_pr_code` outranks photos (never overwritten by photo passes).
- RDW odometer codes 04/07 (illogical) and open recall/export flags become red flags.

## Config
`vet.destination_country` (picks `knowledge/import/<dest>-registration.md` + `<seller>-to-<dest>.md`) and `vet.max_open_asks`: values and defaults in [`config.example.yaml`](../config.example.yaml) `vet:`.

## Data files
- `carhunt/vet/data/wmi.csv` (`wmi,manufacturer,market,confidence`; `market` = `china_jv` | `china_built` | empty). Extend freely; unknown WMIs only produce an info flag.
- `carhunt/vet/data/prcodes_vag.csv` (`code,family,option_key,meaning,confidence`; several rows per package code). Add `prcodes_<brand>.csv` for another brand.

## Tests
`pytest carhunt/vet` — offline, stub cardb.

## Gaps
- No signing tool (owner signs PDFs by hand; see `knowledge/buy/contract-checklist.md` §5).
- Brand mail watcher (warranty replies) belongs to contact's `carhunt watch`.
- Plant-code tables are not bundled (manufacturer-specific); `plant_code` is reported raw.
- Import guides cover destination PT only; other destinations: `knowledge/import/README.md` "Adding a destination".
- Decision UI (👍/🤔/👎 + note) lives in cardb/web (`verdict`), not here.
