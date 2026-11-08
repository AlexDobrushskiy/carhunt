# Document verification (cross-check method + spec table)

Siblings: [contract-checklist.md](contract-checklist.md) · [pickup-day.md](pickup-day.md) · [../pr-codes-vag.md](../pr-codes-vag.md)

Input: whatever the seller sent — inspection/return report (e.g. TÜV/DEKRA lease-return protocol), service proof, battery certificate, registration photos, ad photos and text. Vet agents are read-only: they never message the seller; open questions become `ask` events (`carhunt evidence CAR`) for the outreach agent.

## 1. Cross-check method

- **Read every page yourself** (images: zoom/vision), not another agent's summary.
- Build a cross-check table, one column per document:

| Item | Inspection report | Service proof | Battery cert | Registration / ad |
|---|---|---|---|---|
| VIN | every page footer? type-plate photo? "VIN read, matches papers"? | | | |
| Model / variant | | | | |
| First registration | | | | |
| km + date | | | | |
| Issuer | name, report/order no. | issuer/partner ID, print date | provider, cert no., who ran it | dealer stock no. |

- **VIN on every document**, identical; check digit via `carhunt vin check-digit VIN`, decode via `carhunt vin decode VIN`.
- **km sequence**: order all readings by date; deltas must be plausible (e.g. service 2026-03-01 @ 41,200 → inspection 2026-03-20 @ 41,950 → cert 2026-04-15 @ 41,953 → ad 41,951). Annual rate vs age; a few km while parked at a dealer is normal; a decrease or a jump needs an explanation.
- **Dates**: first reg vs delivery/handover inspection; service intervals kept (OEM fixed interval, e.g. 2-yr); certificate dates after the last km reading.
- **Issuer**: real organisation, report number format consistent, partner/issuer ID present; dealer stock no. matching file names is a good sign.
- **Edit marks / generic pages**: font changes, misaligned fields, missing page numbers, VIN missing from some pages, a page that could belong to any car. Flag any.
- **Harmless inconsistencies** to note, not alarm on: inspection database model label (e.g. sister model name) while type-approval codes (DE HSN/TSN) match; equipment list contradicting itself while a photo settles it; trim-name translations.
- **Plates**: no plate on any doc + inspection took "both plates" at lease return → the car is most likely deregistered → plan transit plates ([../import/README.md](../import/README.md)).
- **Service proof**: campaigns/actions done are listed by code; a known open recall *not* listed = still open → ask for the dealer's campaign printout for the VIN.
- **Battery certificate**: which method (short OBD readout vs full-discharge test), date, km, who ran it; check SoH × net capacity ≈ stated kWh; ask for the original PDF to verify by QR/cert no.
- **Inspection conditions**: "no lift / eingeschränkt" → underbody and HV battery housing unchecked → lift check at pickup ([pickup-day.md](pickup-day.md)).

## 2. Condition claims

- **"Unfallfrei" (accident-free) means only no reportable accident.** Repaints, hail repair, PDR and cosmetic damage can still exist. Ask plainly. Ask: *"Gab es Lackierarbeiten, Hagel- oder Ausbeulreparaturen (PDR)? Bitte offen sagen."* / *"Any repaints, hail or paintless dent repair?"*
- Inspection report items: list every finding (damage, paint-thickness readings per panel or "ohne Auffälligkeiten", tyres + tread, interior, windscreen, missing items) and cost estimates if given.
- **Dealer says "fixed" → compare with photos.** Ad photos may not resolve small panels. A fix you can't see counts as **unproven** → ask for after-repair close-ups of each panel.
- **Polishing can't remove chips.** "Scratches polished out" on a panel the report says had chips means it was touched up/painted or still has chips — ask which.
- Mixed or partial wheel sets: the report's tyre table (size, type, depth per wheel) beats the equipment-list label ("4 winter wheels" can be 2 winter + 2 summer).

## 3. Spec table

Marks: **✅ doc** confirmed (document + page) · **📄 ad** ad text/photos only · **❓** unknown · **❌** not fitted.

| Feature | Status | Source |
|---|---|---|
| Model / power / drive | ✅ … | report p2–3, registration |
| Model year / build | ✅ … | VIN position 10, report |
| Software version | ❓ … | |
| Battery gross/net, SoH | ✅ … | report, battery cert |
| AC / DC charging | ✅ 11 kW · ❓ DC (spec sheet value, cited) | report p3 · OEM spec |
| Heat pump | ✅ … | report, refrigerant label |
| Must-have 1…n | ✅/❌ … | |
| Seats (electric, memory, massage, heating, ventilation) | | |
| Roof, audio, HUD, lights, tailgate, towbar | | |
| Assist / parking / infotainment / comfort packages | | |
| Wheels + tyres (both sets) | | |
| Owners | 📄 ad; registration part II unconfirmed | |
| Warranty / guarantee | 📄 … duration ❓ | |

- One row per feature the buyer cares about; must-haves first, each with page reference.
- Close with: must-haves confirmed? what's missing vs a full-spec car? asks list (one line each).
- Options from photos and PR codes: [../pr-codes-vag.md](../pr-codes-vag.md); direct interior cues beat dealer "full" equipment lists.
- Record in cardb: `cardb fact CAR doc_check="<date>: <verdict>":inspection`, `cardb fact CAR spec_full="<short>":inspection`, options via `cardb opt CAR key=yes:inspection` (don't overwrite options sourced from the seller, PR codes, inspection or the owner — add a fact on conflict).

## 4. Numbers and claims discipline

- **Every computed number** (ownership months, SoH %, km/yr, price deltas, value-loss estimates) is relayed only after re-checking the **date math** and **stating the assumptions** (which dates, which capacity, gross vs net).
- **Every technical claim carries its source** (document + page, or link). Registration date alone doesn't prove a spec; the ad or CoC does.

## 5. Output

- Verdict line: documents consistent? genuine-looking? all for this car? findings cosmetic or substantive?
- Asks (one line each) → `ask` events, e.g. campaign printout for the VIN, number of previous keepers (registration part II), after-repair photos, guarantee terms, original battery-cert PDF, deregistration status + plates, CoC original at pickup.
- On-site list for [pickup-day.md](pickup-day.md): lift check, specific panels, tyre depths.
