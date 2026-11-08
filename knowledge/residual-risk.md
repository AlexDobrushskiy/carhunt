# Residual risk: judging a car's known flaws after coverage

> Snapshot: researched Oct–Nov 2026 (EV run). Prices, laws and tool behaviour drift — re-check anything you act on.

**Tags:** **V** verified (primary/official source or ≥2 outlets) · **A** anecdotal (forum, single secondary source) · **I** inferred. Coverage facts come from [coverage-rules.md](coverage-rules.md); VIN lookups from [vin-sources.md](vin-sources.md); battery from [battery-soh.md](battery-soh.md).

**Core rule: most flaws are a per-VIN question, not a model verdict.** A known fault that is covered free for the likely ownership period is a nuisance, not a dealbreaker. Judge every flaw after coverage, then rate **money** and **breakdown/inconvenience** separately.
WHY: v1 of the EV reliability report treated covered faults as dealbreakers (e.g. a platform-wide charging-unit fault covered by recall + a 15-yr extension); the owner corrected it (2026-10-31) and several verdicts moved up by 0.5.

---

## Procedure (one car)

1. **Pin the car's coverage inputs** (from VIN decode, documents, ad): platform, build date, first-registration date, **first-sale country** (its warranty terms apply), km, service history (network or independent, unbroken?), seller type (dealer in buyer country / foreign dealer / private).
2. **List the known flaws** for the model *and* its platform (shared modules and suppliers). Sources: table below. Include the generic EV ones: 12 V battery / DC-DC, onboard charger, heat pump, HV battery batch recalls.
   - **Platform consistency:** a shared-platform issue gets the same score on every sibling model. Any difference must be explained by supplier/cell batch, plant, build date, or motor/software generation. WHY: owner rule for v2 (2026-10-31): sibling MEB models (VW/Škoda/Audi/Cupra) share modules and suppliers, so separate per-model agents must score them alike via one shared-issues file.
3. **For each flaw, settle coverage for THIS VIN** (not the model):
   - Recall: in the affected build/VIN range? **done / open / not affected** — from a dealer printout or brand VIN checker run with controls.
   - Vehicle warranty left (first-sale country terms): end date and km cap. Does it cover this part?
   - HV-battery warranty: only cells/pack. OBC, DC-DC, motor, inverter, heat pump, 12 V battery are **not** in it.
   - Extension / goodwill: counts only **in writing for this VIN**, honoured in the buyer's country.
   - Extension-by-service (Relax type): chain unbroken?
   - Seller's statutory liability: term (1 yr / 2 yr / PT 18 mo–3 yr) and how enforceable from where the buyer lives.
   - Used-car guarantee: written terms, HV parts in scope, valid in buyer country.
4. **Cost if not covered:** € with source, or "no data". Never invent a figure.
5. **Likelihood and what happens when it hits:** rate (per 1,000 cars, % of complaints) and the consequence: annoyance, limp mode, tow, weeks off the road, use restriction.
6. **Rate the two axes** (rules below). Note that coverage never pays for downtime (no loss-of-use compensation, **V**).
7. **Write the per-VIN question** that would settle the open part (e.g. "dealer printout: is campaign X done?"). Run free checks first; each remaining question becomes one seller ask via `carhunt evidence CAR` (the outreach agent sends it; vet agents never message sellers), or one brand question per [coverage-rules.md §7](coverage-rules.md#7-how-to-ask-the-brand-warranty-end-dates-extension-status-recall-details) (owner approval first).
8. **Roll up:** car-level money risk = worst money row that is not just a per-VIN unknown; breakdown risk = worst breakdown row plus model-level survey data. A verdict rests on both axes plus fit for the buyer, never on the mere existence of a fault.

## Rating rules

| Level | Money (out of pocket after recalls, warranties, written extensions) | Breakdown / inconvenience (tow, limp mode, days without the car, use limits, repeat visits) |
|---|---|---|
| **low** | covered free for the likely ownership period, or rare + cheap (e.g. 12 V battery ~€150–350) | a one-off jump start or tow; annoyance (screen reboot) |
| **medium** | not covered, moderate cost or moderate likelihood (e.g. OBC/DC-DC ~€1.5–3.5k on a car whose 2-yr warranty ended) | covered but with real restrictions or downtime: weeks waiting for parts, repeat failures, an open recall with a one-visit fix not yet done |
| **high** | likely + expensive + not covered | likely tow + weeks off the road; interim restriction (80 % charge cap, park outdoors) **with no fix date**; open recall that fails the buyer-country inspection |

- Coverage moves the **money** axis. Breakdown statistics and owner surveys move the **breakdown** axis; they don't change money. WHY: a fault can cost nothing and still strand the car for weeks (2026-10-31).
- An unknown coverage term in the buyer's country is written "**<country> unconfirmed**" plus who to ask and which document settles it. It is a question, not a score.
- An **open recall** alone is not a walk-away; see [coverage-rules.md §1](coverage-rules.md#1-recalls) for the exceptions.

## Output shape (per car)

```
**Money risk (after coverage): low|medium|high** — <≤15-word reason>
**Breakdown / inconvenience risk: low|medium|high** — <≤15-word reason>

| Flaw | Coverage for this VIN (what · until · transfers? · honoured in buyer country?) [tag] | Cost if not covered [tag] | Likelihood · what happens [tag] | Money | Breakdown | Per-VIN question |
|---|---|---|---|---|---|---|
```
One row per flaw. Put "not affected (build date / batch)" rows in too, with the reason, so the next agent doesn't recheck them.

## Data sources, ranked

| Rank | Source | Use for | Tag |
|---|---|---|---|
| 1 | Dealer VIN printout of campaigns + service record; brand's written answer for the VIN | recall done/open, warranty end dates for this car | V (per VIN) |
| 2 | Brand VIN recall checkers (run with controls: VIN ±1, fake VIN, known positive) | open recall yes/no | V only after controls pass |
| 3 | Official recall DBs: KBA Rückrufdatenbank (DE), EU Safety Gate, RDW (NL, by plate), national lookups (PT recall.motordata.pt), NHTSA recalls (same hardware, US build ranges) | which builds are affected, remedy, interim measures | V (model/build level) |
| 4 | Brand warranty T&Cs / booklets (buyer and first-sale country) | what is covered, conditions, transfer | V |
| 5 | Breakdown and defect statistics: ADAC Pannenstatistik (breakdowns per 1,000 by registration year), TÜV Report (inspection defects; partly usage effects), owner surveys (What Car? "% off the road >1 week", Which?, Consumer Reports) | breakdown axis, model level | V (dataset); press summaries of a dataset = secondary |
| 6 | NHTSA complaint counts (API, per model year, keyword) | whether a fix reduced failures; repeat failures | V for counts, A per report |
| 7 | Specialist press (electrive, InsideEVs, national auto clubs' news) | programme announcements, country scope | V if ≥2 outlets, else A |
| 8 | Owner forums (goingelectric, motor-talk, model forums), repair-shop blogs | symptoms, repeat failures, parts waits, goodwill %, repair prices | **A** — never for rates |

---

## Worked example — **example, Oct 2026, verify before use**

**Platform-wide charging / 12 V unit fault: Hyundai/Kia E-GMP "ICCU"** (one box under the rear seat does AC charging, 12 V DC-DC and V2L; when it fails both charging and the 12 V supply go). Car: Ioniq 5 77.4 kWh, built before Apr 2024, first sold in DE, buyer in PT, late 2026.

| Flaw | Coverage for this VIN | Cost if not covered | Likelihood · what happens | Money | Breakdown | Per-VIN question |
|---|---|---|---|---|---|---|
| ICCU failure (built ≤ Apr 2024) | Recall (KBA 13860 / Hyundai 41D022/033; US 24V-868 replaced 24V-204 after re-failures): software + new ICCU and fuse if a fault code is stored; free, VIN-bound **V** · base warranty DE 5 yr (not PT's 7) → ~2028 **V** · ICCU extension 15 yr / 300k km: FI/DK/DE **V**, **PT unconfirmed** | €1,500–2,000 incl. labour **A** | ADAC 19.5–28.2 breakdowns per 1,000 (EV avg 3.8), no post-fix drop **V** (secondary for 2026 ed.) · drive power cut ~15–45 min after warning → tow; parts waits weeks to months **A** | **low** | **high** | Dealer printout: recall done? ICCU replaced before, how often? Brand in PT, in writing: does the 15-yr ICCU extension apply to this VIN after import? |
| ICCU failure (facelift, built > Apr 2024) | Base warranty only (no extension; brand says "optimised design") **V** | €1,500–2,000 after warranty **A** | US MY2025: 188 ICCU complaints, so not eliminated **V** count | low–medium | medium | First-registration date (starts the warranty clock) |
| Repeat ICCU failure after replacement | Same as first failure | — | ~30 per model year in NHTSA complaints describe a repeat **A** | low | medium | How many ICCU replacements? Walk away from a car with two |
| 12 V battery flattened / worn | 2 yr only **V** | ~€150–300 **A** | 12 V ≈ 20 % of faults in a UK owner survey **V** · jump start | low | low | 12 V battery age; any tow-ins; ~14–15 V at the 12 V battery in "ready" |

**Roll-up:** Money **low** (covered to ~2028 even if PT refuses the extension; exposure is ~€2k only after that). Breakdown **high** (tow + weeks off the road remain likely). The 2026-10-31 report moved this model from 3/5 to 3.5/5 on that basis: still a candidate, conditional on recall done + extension confirmed in writing.

**What generalises:** the same split applies to any combined charger/DC-DC unit (VW group "OCDC": US recalls 93CJ/93FR on 2024 builds, no EU recall in Oct 2026, out of warranty on 2-yr-brand cars → money **medium**, breakdown low per ADAC). Check the 12 V system on every EV: 12 V / DC-DC trouble was the most common EV breakdown cause across the models researched (2026-10-31).
