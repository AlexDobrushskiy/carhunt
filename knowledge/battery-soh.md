# Battery health (SoH) — evidence, asks, DIY OBD

> Snapshot: researched Oct–Nov 2026. Prices, laws and tool behaviour drift — re-check anything you act on.

Tags: **V** verified live on the official/provider source · **A** anecdotal/secondary (forum, press, user report) · **I** inferred, not from the sources — verify.

Related: [vin-sources.md](vin-sources.md) (brand registry, recall tools) · [coverage-rules.md](coverage-rules.md) (what the HV-battery warranty does/doesn't cover) · [buy/pickup-day.md](buy/pickup-day.md). Record results: `cardb fact CAR battery_soh="<value> (<method>, <date>, <km>)":<source>`; missing evidence → `ask` event via `carhunt evidence CAR` (vet agents never message sellers).

**Why it matters:** the traction battery is ~40% of a used EV's value. No paid VIN history report measures it.

---

## 1. Evidence ranking (best → worst)

| # | Evidence | Proves | Doesn't prove | Tag |
|---|---|---|---|---|
| 1 | **Aviloo PREMIUM** certificate (full 100%→10% drive with a rented box) or **Aviloo FLASH** (3-min OBD test, dealer-only, ±3% vs PREMIUM) | independent measured SoH, dated, with VIN + km; PREMIUM usable in disputes; FLASH can carry an Aviloo battery guarantee (up to €3k) via dealers on Aviloo Connect | cell faults outside the test; anything after the test date | V |
| 2 | **OEM dealer battery certificate** (VW group "Batteriezertifikat", BMW "Battery Health Quick Report", Mercedes XENTRY "Batterie-Zertifikat", Kia/Hyundai GDS printout) | manufacturer-binding BMS value; warranty-relevant | independence (dealer sells the car) | A |
| 3 | **Brand health-check printouts** (e.g. Toyota yearly EV Health Check; BE Car-Pass optional SoH since 2026) | pass/fail or %, and (Toyota) that the battery-cover extension chain is intact | precise capacity if only "Pass" | A / V (Car-Pass) |
| 4 | **Car-app / in-car screenshot**: charge %, range estimate, any SoH menu, warnings | no warnings; plausible range for the % shown | capacity (range depends on driving/temperature) | A |
| 5 | **Charging-session sample** (§2) | rough usable capacity (±5% or worse) | anything precise; loss assumptions dominate | A/I |
| — | Seller's word ("100%", "like new") | nothing | — | — |

WHY the ladder bottoms out at the app screenshot: non-native sellers often don't understand the charging-session ask, while an app screenshot is usually enough to move on.

Benchmarks (dated examples, not norms): VW MEB ~93% at 30–50k km (owner sheet, ~169 cars, A); Kia EV6 at 27k km Aviloo 97.9% while BMS showed 100% (V); Toyota bZ4X at 30k km 92% (third-party certificate, V); Toyota's own target is 90% after 10 years (A). Typical HV warranty: 8 yr / 160k km, defect only below 70% (VW doc V; others similar A).

## 2. Charging-session sample — formula

```
E_batt   = E_meter × (1 − loss)                # energy that reached the pack
C_usable = E_batt / (SoC_end − SoC_start)       # SoC as fractions, car-displayed
SoH      = C_usable / C_usable_new              # C_usable_new = net capacity from the spec
```

- Loss: DC fast ≈ 3–8%, AC/wallbox ≈ 8–15% (**I** — not measured). Always report a **range**, never a point.
- Use a big window (start ≤30%, end at a displayed **100%**), a warm pack, and the charger's own kWh (receipt/app photo), not the seller's memory.
- Use the **net/usable** capacity of the exact variant (not gross; check the battery code — see the China-pack case in [vin-sources.md](vin-sources.md#6-wmi--market-flags)).

**Worked example:** car with 77.0 kWh usable when new; DC session 20% → 100%, charger shows 60.5 kWh.
- E_batt = 60.5 × (0.92 … 0.97) = 55.7 … 58.7 kWh
- C_usable = E_batt ÷ 0.80 = 69.6 … 73.3 kWh
- SoH ≈ 69.6/77 … 73.3/77 = **90% … 95%** → "roughly 90–95%, not proof; ask for #1–#3".

Without the loss correction it would read 98% — the classic way to flatter a battery. Re-check the arithmetic before relaying; agent-computed numbers spread wrong easily.

## 3. How to ask (simple asks for non-native sellers)

One ask per message, in this order; stop at the first that arrives. Short, plain words — the outreach agent translates.

1. "Do you have a battery health report or certificate? A photo is fine."
2. (dealer) "Can you run an Aviloo FLASH test or print the brand battery certificate before I come?"
3. "Can you send a screenshot of the car app: battery %, range, and any warnings?"
4. Only if 1–3 fail and the seller writes well: "Next time you charge: photo of the charger screen at the end (kWh) and the car's % before and after."
5. Brand-specific: Kia/Hyundai "EV menu → battery / State of Health" screen if present; Toyota "all yearly EV Health Check printouts"; Mercedes EQA/EQB "is the battery recall done (date/km)?" (see [vin-sources.md §9](vin-sources.md#9-brand-registry)).

## 4. Red flags

- **No evidence AND the seller refuses any test** (Aviloo, dealer readout, OBD read at viewing).
- **SoH < 90% on a young car** (≤3–4 yr).
- **"100%" without a document.**
- **E-GMP (Kia/Hyundai) caveat:** the BMS shows **100% until the hidden buffer is used up** (reported up to ~7% real loss, A; one test: BMS 100% vs Aviloo 97.9%, V). So 100% = "no warning sign", not proof; **anything below 100% is a red flag** (real loss is already larger).
- Mercedes EQA/EQB: SoH can't be read DIY — need dealer readout or Aviloo; plus recall status.
- Large cell-voltage spread on a DIY read (MEB: >~10 mV at rest is suspicious, A); BMS fault codes present.
- Range in the app far below siblings at the same % and season (I).

## 5. Where tests are available

| Option | Where | Price (2026-10/11) | Tag |
|---|---|---|---|
| Aviloo PREMIUM (box shipped, 100%→10% within 7 days) | B2C shop ships to AT, BE, CZ, DK, FI, FR, DE, IT, LU, NL, NO, SK, SE, CH — **not PT/ES**. Box can go to a different address (the seller) | €99 incl. DE VAT; "Early Access" €49 (100%→1%) for some newer models | V |
| Aviloo FLASH (3 min, OBD) | **dealers/workshops with a B2B licence only**; many DE dealers. No PT/ES partners listed by Aviloo, but its guarantee reached PT/ES in Sep 2026; at least one PT workshop runs FLASH; Euromaster ES rollout reported (A). Ask the selling dealer or Aviloo support | dealer-set; PT workshop €69–79 + VAT | V/A |
| No consumer app works with your own dongle; Aviloo Connect is a dealer/fleet dashboard | — | — | V |
| ADAC test centre (DE) | car must be brought there | Hamburg €149 member / €164 incl. fault codes + FLASH; others €79–286 | A |
| TÜV NORD (DE) | station; dealer brings the car | €199; Carly + TÜV Nord CARA battery check at TÜV Nord stations | A / V |
| DEKRA / TÜV SÜD / GTÜ (DE) | station or partner; GTÜ battery check = Aviloo PREMIUM via partner | DEKRA battery quick test ~€100 | A / V |
| PT mobile inspectors | VerifiCar battery scan (CARA tool), mainland; 1in.pt reads SoH where tooling allows | VerifiCar €70; 1in.pt €150–250 incl. travel | V |
| OEM dealer readout | any brand dealer; VW: capacity check on request is not warranty-covered (paid) | Mercedes ~€120 (value) – €190 (report), A | A |

A remote buyer's realistic route: ask the **selling dealer** to run FLASH or print the OEM certificate; private sellers abroad: Aviloo PREMIUM shipped to them (if they'll drive it down) or an ADAC/TÜV visit.

## 6. DIY OBD at a viewing

**Read-only rules (non-negotiable):**
- Ask permission before plugging in. Read with the car in ready/ignition-on.
- **Never clear codes** (erases the fault history), never code, adapt, run service resets, "battery registration" or bi-directional tests. OBDeleven, Carly, BimmerCode and Car Scanner's coding menu can all write to the car. Reading doesn't affect warranty; coding can.
- **Unplug the dongle when done** — left in, it keeps modules awake and drains the 12 V battery.

**Kit (iPhone needs BLE):** vLinker MC+ (~€71–72, most versatile) or OBDLink CX (~€100, best for BMW/MINI) or Veepeak OBDCheck BLE+ (~€46, cheapest that works) + **Car Scanner ELM OBD2** Pro (€8.99 lifetime). Skip classic-BT/MFi-only dongles (OBDLink MX+, vLinker FS) for BLE-only apps, €10 ELM327 clones (lack the CAN commands EV reads need), OBDeleven (own app only, no EV SoH). CAN-FD not needed for the platforms below. Android has more apps (EVNotify, Torque) (V).

| Platform | App → value | Trust | Verdict | Tag |
|---|---|---|---|---|
| **VW MEB** (ID.3/4/5, Q4, Enyaq, Born/Tavascan) | Car Scanner (MEB profile) → Gateway 19 "Max energy content" (Wh); SoH = MEC ÷ net capacity (77 kWh pack: ÷77). CellPulse (free, iOS) → usable capacity + cell balance. OBDeleven free plan shows the same MEC | real BMS estimate ±1–3 kWh; dips in winter, jumps after recalibration | **Do it.** 77-kWh pack: ≥72 kWh normal at 2–4 yr; <67 kWh → ask for Aviloo; cell delta <10 mV | A/V |
| **Hyundai/Kia E-GMP** (EV6, Ioniq 5/6) | Car Scanner (Hyundai/Kia EV profile) → BMS "SOH" %, remaining energy, cell voltages | coarse — 100% until buffer used | 100% = no warning; **<100% = red flag**; >100k km → Aviloo anyway | V/A |
| **Toyota bZ4X / Subaru Solterra** | Car Scanner → SoC, cell voltages, temps; capacity only via unverified custom PID | low (even SoC mis-scales) | balance/fault check only; ask for Toyota/Aviloo certificate | A |
| **Mercedes EQA/EQB** | Car Scanner → live HV V/A/temps only. **No app decodes SoH.** Carly "Battery Check" = 12 V battery. iCarsoft MB V3 handheld reads BMS capacity in As (÷3600 → Ah vs nominal), one user report | — | **not DIY-able**; dealer XENTRY or Aviloo | A |
| **BMW / MINI** (incl. Countryman E U25) | **EVScanner** (€24.99 BMW+MINI unlock; free compatibility check first) → pack + per-cell BMS SoH | real BMS value | do it; run the free compatibility check on the car before paying | V |
| **XPeng G6** | Car Scanner + community custom PIDs (header 704/resp 784, SoH PID `22011A1` or `22110A1`, value = B4:B5 ÷ 10) | BMS value; less reliable on LFP (flat voltage curve); untested on a real car | try it; else XPeng service printout / Aviloo | V (profile) / A |
| Others (Tesla, Renault, Stellantis, …) | not researched | — | check the app's supported list; prefer #1–#3 evidence | I |

A better DIY figure needs the car for a day (MEB counter method: kWh charged−discharged ÷ ΔBMS-SoC, ~±3%) — not feasible at a viewing (A).

## 7. 12 V battery (every EV)

12 V / DC-DC trouble is the most common EV breakdown cause (A). On every car:
- Ask the 12 V battery's age and whether the car was ever towed in / wouldn't wake.
- At the viewing, measure at the 12 V battery terminals with the car in **ready**: expect **~14–15 V** (DC-DC charging). Car off and rested: ~12.4–12.7 V is healthy (I).
- Warnings on wake-up, slow wake, or a dealer 12 V replacement in the service history → ask why.

## 8. PHEV / HEV / ICE equivalents

Short pointers; mostly **I** (not researched) — verify per model.

| Powertrain | Evidence ladder | Tag |
|---|---|---|
| **PHEV** | Brand dealer HV-battery readout; Aviloo coverage for some PHEVs (check its vehicle list); charge sample as §2 on the small pack (bigger relative error); plus everything for ICE below; ask how often it was charged (never-charged PHEVs = ICE wear) | I |
| **HEV** (full hybrid) | Brand **hybrid health check** printout (Toyota/Lexus run yearly hybrid checks tied to hybrid-battery cover extensions, I); OBDeleven free "Hybrid battery check" rates Toyota/Lexus hybrid block balance/temps (V); Dr. Prius / Hybrid Assistant (Android) (A) | V/A/I |
| **ICE (petrol/diesel)** | Brand service printout with km trail; **timing belt** replacement invoice (km/years per maker interval) or chain noise on cold start; **compression test** report on older/high-km engines; **DPF** (diesel): soot load / regeneration history via OBD, short-trip history, no "DPF delete"; gearbox service (DSG/automatic oil change) invoices; cold-start video (smoke, rattle); oil leaks on underbody photos | I |

Same read-only OBD rules apply on any powertrain.
