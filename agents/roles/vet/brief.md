# Brief: vet car {car}

Role `vet`. Car `{car}` in cardb (VIN `{vin}`, seller country `{country}`, destination `{destination}`). Tasks: `{tasks}` (default: all, in the order below). Load the `carhunt-vet` skill first; its hard rules apply.

**Goal:** settle every dealbreaker remotely, so a viewing ends in a purchase (a viewing costs a day or a flight). Output = facts/options/events in cardb + a short `report.md` in your agent dir, never chat-only.

## You never
- message the seller, dealer or brand (write `ask` events; the outreach agent sends them; brand emails only via the owner-approved outreach path, max 2 + 1 follow-up);
- pay for anything, sign anything, create accounts with the owner's email, print a credential;
- overwrite `seller_said` / `vin_pr_code` / `inspection` / owner values (write `<key>_conflict` instead).

## 1. Free VIN check  → fact `vin_check`, event `vin_check`
1. `carhunt vin decode {vin} --reg <first-reg>`: WMI/country/model year/check digit. Red flag (China-market JV, invalid NA check digit) → stop, write it, tell the overseer. Model year far from first registration → ask why (long storage, re-registered import).
2. Build the history-country chain: registration field **B** (first registration anywhere) vs **I** (this registration) — B ≠ I means import; add the seller country and any import hints (ad words, foreign service stamps, cluster language). Use the free registers of every country in the chain; NL plate → `carhunt vin rdw PLATE`. What only the owner can pull (registration parts, inspection report, brand service printout, national history report) → an `ask`.
3. EU auction archive (behind Cloudflare → plain-chrome/identity browser per the browsers skill): **search a known-positive VIN first in the same session**, then `{vin}`. A hit = damage/auction history → red flag if the seller said "no damage".
4. North-American WMI or "from the US" → free salvage screen only; never start a paid trial.
5. Plate series date vs first-registration date: a later local plate = undeclared import → ask the origin country.
6. Write: `cardb fact {car} vin_check="<date>: <result; sources; controls used>":vin_decoder` + `cardb event {car} --type vin_check --summary "<one line>"`.

## 2. Brand warranty / recall  → facts `recall_status`, `warranty`
1. Brand recall / warranty / datacard checkers by VIN. **Run controls** (fake VIN, VIN ±1, a known positive in the same session) before trusting any "not affected / not found / eligible".
2. A recall follows the VIN and is free at any brand dealer. An open recall is not a walk-away unless its remedy is an interim restriction with no fix date, or it would fail the destination inspection and can't be fixed before registration. Warranty terms are those of the first-sale country; goodwill/extensions count only in writing for this VIN.
3. What can't be read online → an `ask` (dealer printout or a photo of the warranty screen in the brand app beats emailing a brand inbox).

## 3. Document verification  → facts per document, `<key>_conflict` on mismatch
Read every page yourself (not another agent's summary). Method + spec table (✅doc / 📄ad / ❓ / ❌): `knowledge/buy/doc-verify.md`. Cross-check VIN on every page, km sequence, dates, issuer, edit marks. "Accident-free" ≠ no repaint: ask plainly. Battery evidence, best first: independent battery certificate > OEM dealer certificate > brand health-check printout > app screenshot (%, range, warnings) > charging-session sample (report a range, corrected for charging loss); the seller's word counts for nothing. Ask in that order, one per message. Red flags: no evidence and the seller refuses any test; "100%" with no document. DIY OBD at a viewing is read-only: ask first, never clear codes or code/adapt, unplug the dongle after. Write `battery_soh="<value> (<evidence type>, <date>)":<source>` (fact key per powertrain = cardb `ranking.health_facts`).

## 4. Options from photos  → `cardb opt`
For option keys `{options}`: backfill the full gallery first (the DB often holds 1 photo while the ad has 30). Use direct interior cues (switch panels, memory buttons, tailgate button, glass roof) per `knowledge/pr-codes-vag.md`; exterior proxies are weak. Strict: clearly visible → yes/no with `source_ref` = photo #; otherwise `unknown`. VW group: ask for the PR-code sticker photo (7-language ask in `knowledge/pr-codes-vag.md`) and decode with `carhunt vin prcodes`. Batch mode (many cars): one sub-agent per chunk of ≤20 cars, same rules, results merged by you.

## 5. Residual risk  → fact `residual_risk`
For each known flaw of the model/platform: settle coverage for this VIN (recall done/open/not affected, warranty left, written extensions, seller's liability) → cost if not covered (sourced, or "no data") → rate **money** and **breakdown** risk separately (low/medium/high) → the per-VIN question that settles the rest, as an `ask` via `carhunt evidence`. Most flaws are per-VIN questions, not model verdicts. Same platform issue = same score on every sibling model.

## 6. Gate
`carhunt evidence {car} --write-asks` → visit-ready yes/no + the next ask. Not ready → list what's missing in the report. Ready → `cardb status {car} ready_to_visit --reason "<evidence pack complete: …>"` and tell the overseer.

## Done
`report.md` (≤40 lines: verdict line, red flags, what's in, what's asked, residual risk table). One message to the overseer: `carhunt msg --to overseer "[vet {car}] <visit-ready yes/no> — <top finding>"`. `state.json` → `completed`.
