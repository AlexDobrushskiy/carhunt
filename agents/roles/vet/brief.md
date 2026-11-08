# Brief: vet car {car}

Role `vet`. Car `{car}` in cardb (VIN `{vin}`, seller country `{country}`, destination `{destination}`). Tasks: `{tasks}` (default: all, in the order below). Load the `carhunt-vet` skill first; its hard rules apply.

**Goal:** settle every dealbreaker remotely, so a viewing ends in a purchase (a viewing costs a day or a flight). Output = facts/options/events in cardb + a short `report.md` in your agent dir, never chat-only.

## You never
- message the seller, dealer or brand (write `ask` events; the outreach agent sends them; brand emails only via the owner-approved outreach path, max 2 + 1 follow-up);
- pay for anything, sign anything, create accounts with the owner's email, print a credential;
- overwrite `seller_said` / `vin_pr_code` / `inspection` / owner values (write `<key>_conflict` instead).

## 1. Free VIN check  → fact `vin_check`, event `vin_check`
1. `carhunt vin decode {vin} --reg <first-reg>`: WMI/country/model year/check digit. Red flag (China-market JV, invalid NA check digit) → stop, write it, tell the overseer. Model year far from first registration → ask why (long storage, re-registered import).
2. Pick sources by the car's history countries (first-reg country, seller country, import hints): `knowledge/vin-sources.md` §1–3. NL plate → `carhunt vin rdw PLATE`. BE → verify the Car-Pass. FR → ask for the HistoVec link. DE → no register; ZB II, HU report, dealer service printout.
3. EU auction archive (carsbat-type, behind Cloudflare → plain-chrome/identity browser per the browsers skill): **search a known-positive VIN first in the same session**, then `{vin}`. A hit = damage/auction history → red flag if the seller said "no damage".
4. North-American WMI or "from the US" → free salvage screen (EpicVIN preview / stat.vin). Never take the $1 trial (auto-renews at ~$100/month).
5. Plate series date vs first-registration date: a later local plate = undeclared import → ask the origin country.
6. Write: `cardb fact {car} vin_check="<date>: <result; sources; controls used>":vin_decoder` + `cardb event {car} --type vin_check --summary "<one line>"`.

## 2. Brand warranty / recall  → facts `recall_status`, `warranty`
1. Brand registry in `knowledge/vin-sources.md` §9: recall checker, warranty/extension checker, datacard route. **Run a control** (fake VIN, VIN ±1) before trusting any "not affected".
2. Judge by `knowledge/coverage-rules.md`: recalls follow the VIN EU-wide and are free; open recall is not a walk-away unless it carries an interim restriction with no fix date or fails the destination inspection; warranty terms are those of the first-sale country; goodwill/extension counts only in writing for this VIN.
3. What can't be read online → an `ask` (dealer printout or a photo of the warranty screen in the brand app beats emailing a brand inbox).

## 3. Document verification  → facts per document, `<key>_conflict` on mismatch
Read every page yourself (not another agent's summary). Method + spec table (✅doc / 📄ad / ❓ / ❌): `knowledge/buy/doc-verify.md`. Cross-check VIN on every page, km sequence, dates, issuer, edit marks. "Accident-free" ≠ no repaint: ask plainly. Battery evidence ranking: `knowledge/battery-soh.md` (write `soh="<value> (<evidence type>, <date>)":<source>`).

## 4. Options from photos  → `cardb opt`
For option keys `{options}`: backfill the full gallery first (the DB often holds 1 photo while the ad has 30). Use direct interior cues (switch panels, memory buttons, tailgate button, glass roof) from `knowledge/pr-codes-vag.md` §5–6; exterior proxies are weak. Strict: clearly visible → yes/no with `source_ref` = photo #; otherwise `unknown`. VW group: ask for the PR-code sticker photo (7-language ask in §4) and decode with `carhunt vin prcodes`. Batch mode (many cars): one sub-agent per chunk of ≤20 cars, same rules, results merged by you.

## 5. Residual risk  → fact `residual_risk`
Apply `knowledge/residual-risk.md` to this VIN: known flaws for the model/platform → coverage for this VIN → money risk and breakdown risk rated separately → per-VIN question for the seller (as an `ask`). Most flaws are per-VIN questions, not model verdicts.

## 6. Gate
`carhunt evidence {car} --write-asks` → visit-ready yes/no + the next ask. Not ready → list what's missing in the report. Ready → `cardb status {car} ready_to_visit --reason "<evidence pack complete: …>"` and tell the overseer.

## Done
`report.md` (≤40 lines: verdict line, red flags, what's in, what's asked, residual risk table). One message to the overseer: `carhunt msg overseer "[vet {car}] <visit-ready yes/no> — <top finding>"`. `state.json` → `completed`.
