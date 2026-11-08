---
name: carhunt-vet
description: Use when vetting or buying a specific used car in a carhunt setup — VIN decode / check digit / market flags, free history checks per country, NL plate lookup (RDW), VW-group PR codes, battery-health evidence, recall/warranty coverage, residual risk, document verification, the per-car evidence pack and visit-ready gate, contract review, deposit/payment safety, pickup day, import + registration, and closing the hunt. Triggers - "check this VIN", "is this car visit-ready", "what's missing for car N", "decode these PR codes", "review the contract", "is this dealer legit", "how do I import from DE", "pickup checklist".
---

# carhunt-vet

Facts about one car → evidence pack → visit-ready gate → buy → import. Knowledge lives in `knowledge/` (repo root); tools are `carhunt vin …` and `carhunt evidence`. Facts go to cardb, never to chat only.

## Hard rules (why in brackets)
- **Never message a seller, dealer or brand yourself.** Missing evidence → `carhunt evidence CAR --write-asks` writes `ask` events; the outreach agent sends them and closes them with `ask_answered`. (Vet agents are read-only; one channel owner per seller avoids double messages.)
- **Own free checks first, then ask; one ask per message, fixed order; skip what the ad or photos already show.** (Short asks get answers; a 4-question opener got none, 2026-11-03.)
- **Control lookup before trusting any checker:** fake VIN, VIN ±1 digit, a known-positive VIN in the same session. (A brand recall tool said "not affected" for a fake VIN; a history preview showed records for a made-up VIN, 2026-10-31.)
- **No paid report or paid option decode without the owner's OK for that car.** Paid reports only for finalists, bought in bulk on the cheapest market site. (€25 × dozens of cars; owner ruling 2026-11-05.)
- **Never create site accounts with the owner's email or keep passwords in files.** Credentials only via `carhunt secret` / the creds helper, never printed. (A subagent stored a decoder password in a scratchpad, 2026-11-04.)
- **Never overwrite a stronger source.** `seller_said`, `vin_pr_code`, `inspection`, owner > `photo` > `ad_text`/`ad_spec` > `agent_inference`. On conflict keep the value and write a `<key>_conflict` fact. When in doubt, `unknown`. (A wrong "no" hides a good car, 2026-11-04.)
- **Every number you relay is re-derived with its date math and assumptions; every technical claim carries its source.** (A wrong 11 kW claim spread into 3 briefs, 2026-11-03.)
- **Personal documents** (contracts, IDs, signatures, registration scans) stay in the scratchpad, never in the repo, cardb notes or chat logs.

## Tools
| command | does |
|---|---|
| `carhunt vin decode VIN [--reg YYYY-MM] [--vpic]` | WMI, country, model year, check digit, flags (China-market JV = red, North America = salvage screen). Exit 2 on a red flag |
| `carhunt vin check-digit VIN` | expected position-9 digit (mandatory only for NA/China VINs) |
| `carhunt vin rdw PLATE` | NL open data: import date, odometer verdict, open recall (free, no key) |
| `carhunt vin prcodes CODES…` | VW-group sticker codes → options + the `cardb opt` line (source `vin_pr_code`) |
| `carhunt evidence CAR [--write-asks] [--max-asks N]` | evidence-pack state, visit-ready yes/no (exit 0 ready, 4 not), next ask(s) |
| `python -m carhunt.vet.md2html report.md` | phone-friendly HTML of a report (V/A/I pills, risk pills) |
| `cardb fact CAR key=value:source` · `cardb opt CAR key=yes:photo:#3` · `cardb event CAR --type vin_check --summary …` | write results |

## Evidence pack (ask order) and fact keys
`registration_doc` → `vin` (car field) → own checks `vin_check` → `service_history` → `battery_soh` (BEV/PHEV) → `recall_status` → `odometer_photo` → `charging_inlet` (imports, China/US VINs) → `warranty` → `accidents` → optional `tyres`, `video_walkaround`, `history_report` (finalists).
A fact value starting `refused` = refusal (red flag); `unknown|pending|asked|missing` = not in yet. Visit-ready = all required items in, no refusal, no red VIN flag, no open `*_conflict`.

## Where to look
| question | file |
|---|---|
| which checks for this car / country / brand | `knowledge/vin-sources.md` |
| battery evidence, charging-sample formula, OBD | `knowledge/battery-soh.md` |
| options from sticker or photos | `knowledge/pr-codes-vag.md` |
| is this fault covered; open recall = walk away? | `knowledge/coverage-rules.md`, `knowledge/residual-risk.md` |
| documents the seller sent | `knowledge/buy/doc-verify.md` |
| contract, deposit, pickup, closing | `knowledge/buy/*.md` |
| import + registration | `knowledge/import/README.md` → `<dest>-registration.md` + `<seller>-to-<dest>.md` (`vet.destination_country` in config) |

Agent briefs: `agents/roles/vet/brief.md` (per-car vetting), `agents/roles/buy/brief.md` (from accepted offer to registered car).
