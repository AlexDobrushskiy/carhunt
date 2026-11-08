---
name: carhunt-vet
description: Use when vetting or buying a specific used car in a carhunt setup — VIN decode / check digit / market flags, free history checks per country, NL plate lookup (RDW), VW-group PR codes, battery-health evidence, recall/warranty coverage, residual risk, document verification, the per-car evidence pack and visit-ready gate, contract review, deposit/payment safety, pickup day, import + registration, and closing the hunt. Triggers - "check this VIN", "is this car visit-ready", "what's missing for car N", "decode these PR codes", "review the contract", "is this dealer legit", "how do I import from DE", "pickup checklist".
---

# carhunt-vet

Facts about one car → evidence pack → visit-ready gate → buy → import. Knowledge lives in `knowledge/` (repo root); tools are `carhunt vin …` and `carhunt evidence`. Facts go to cardb, never to chat only.

## Hard rules
- **Never message a seller, dealer or brand yourself.** Missing evidence → `carhunt evidence CAR --write-asks` writes `ask` events; the outreach agent sends them and closes them with `ask_answered`. Brand/dealer emails only with the owner's OK of the exact text, max 2 + 1 follow-up.
- **Own free checks first, then ask; one ask per message, fixed order; skip what the ad or photos already show.**
- **Control lookups before trusting any checker's "not affected / not found / eligible":** fake VIN, VIN ±1 digit, a known positive in the same session. Only a result that differs from the controls counts; log the controls with it.
- **No paid report, paid option decode or paid trial without the owner's OK for that car.** Paid history reports only for finalists.
- **Never create site accounts with the owner's email or keep passwords in files.** Credentials only via `carhunt secret` / the creds helper, never printed.
- **Never overwrite a stronger source.** `seller_said`, `vin_pr_code`, `inspection`, owner > `photo` > `ad_text`/`ad_spec` > `agent_inference`. On conflict keep the value and write a `<key>_conflict` fact. When in doubt, `unknown`.
- **Every number you relay is re-derived with its date math and assumptions; every technical claim carries its source.**
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

## Checks
- **History countries:** registration field B (first registration anywhere) vs I (this registration); B ≠ I = import. Use the free registers of every country in the chain (NL: `carhunt vin rdw`); the rest is an `ask`.
- **Battery evidence, best first:** independent battery certificate > OEM dealer certificate > brand health-check printout > app screenshot > charging-session sample (`SoH ≈ kWh_charged × (1 − loss) ÷ ΔSoC ÷ net capacity`, reported as a range). Seller's word counts for nothing. Red flags: no evidence and refuses any test; "100%" with no document. DIY OBD is read-only: ask first, never clear codes or code/adapt, unplug the dongle after.
- **Coverage:** a recall follows the VIN and is free; an open recall is a walk-away only with an interim restriction and no fix date, or if it fails the destination inspection and can't be fixed before registration. Warranty terms = first-sale country. Goodwill/extensions count only in writing for this VIN.
- **Residual risk:** per flaw settle coverage for this VIN, then rate money and breakdown risk separately (low/medium/high); the open part becomes a per-VIN `ask`.

## Where to look
| question | file |
|---|---|
| options from sticker or photos, PR-code sticker ask | `knowledge/pr-codes-vag.md` |
| documents the seller sent | `knowledge/buy/doc-verify.md` |
| contract, deposit, pickup, closing | `knowledge/buy/*.md` |
| import + registration | `knowledge/import/README.md` → `<dest>-registration.md` + `<seller>-to-<dest>.md` (`vet.destination_country` in config) |

Agent briefs: `agents/roles/vet/brief.md` (per-car vetting), `agents/roles/buy/brief.md` (from accepted offer to registered car).
