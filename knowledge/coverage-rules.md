# Coverage rules: what pays when a used car breaks (EU)

> Snapshot: researched Oct–Nov 2026 (EV run). Prices, laws and tool behaviour drift — re-check anything you act on.

**Tags:** **V** = verified from a primary/official source (EU Commission, statute text, court/arbitration decision, brand T&Cs) or ≥2 independent outlets · **A** = anecdotal (forum, single secondary source) · **I** = inferred (our reading, not stated by a source).
**Scope:** EU/EEA buyer, used car 1–4 years old, bought from a dealer or private seller, possibly in another member state. PT- and DE-specific rows are marked. Applying this per car: [residual-risk.md](residual-risk.md). Recall/VIN lookups: [vin-sources.md](vin-sources.md). Battery evidence: [battery-soh.md](battery-soh.md). Contract wording: [buy/contract-checklist.md](buy/contract-checklist.md).

**The rule that changes most verdicts:** the car keeps the warranty terms of the country where it was **first sold** (§2). On a 2023–24 car bought in late 2026, a 2-year manufacturer warranty (VW group except Cupra, Mercedes, Peugeot base) is already over. What normally remains: HV-battery warranty, recalls, multi-year brand warranties, any extension actually bought, and the seller's statutory liability.

---

## 1. Recalls

| Rule | Tag |
|---|---|
| A recall is bound to the **VIN**, free at any authorised dealer, and stays open until done. No source gives an expiry. | V (IMT/ACAP press release 27 Feb 2026; DECO) |
| Any authorised dealer in **any EU country** must do it, whatever country sold the car. Refusing warranty/recall work on a car bought in another member state is a sales restriction contrary to EU competition law; no extra admin that delays the work. | V ([EC motor-vehicle FAQ](https://competition-policy.ec.europa.eu/system/files/2021-09/FAQ_application_of_EU_antitrust_rules_in_the_motor_vehicle_sector_en.pdf), Q5 + fn 10) |
| Re-registration in another country does not close it. Recall letters go to the keeper registered in the origin country, so an imported car must be checked **by VIN**, not by the new plate. | V (VIN-bound) / I (letters) |
| Whether a national lookup shows cars first sold abroad depends on the brand's importer feeding it. Always also run the brand's own VIN tool and ask a dealer to run the VIN in the brand system. | A |
| No loss-of-use compensation while the car waits for a recall fix. | V (VW warranty terms §6.3) |
| **PT since 1 Mar 2026:** an open recall classed "grave"/"muito grave" (safety, emissions) is written on the periodic-inspection (IPO) sheet and the car **fails**. Basis: IMT Deliberação 723/2020. Lookup: recall.motordata.pt (plate or VIN, free). | V (IMT, Lexpoint) |
| PT import inspection (atribuição de matrícula): whether the recall rule also applies there is **not stated**. Safest: have every open recall done in the origin country **before export** and keep the dealer work order with the campaign code. | A |

**Open recall ≠ walk-away.** A free one-visit fix is low risk; ask the seller to have it done before handover or do it after. Walk away (or price it in) only when:
- the remedy is an **interim restriction with no fix date** (charge cap at 80 %, "park outdoors", "don't charge indoors"), or parts are back-ordered for months, or
- the recall is serious enough to **fail the buyer-country inspection** (PT since 1 Mar 2026) and can't be fixed before registration.

WHY: an EV run hit both an SUV with a battery-swap recall under an 80 % cap / outdoor-parking interim and a Toyota with an undisclosed open recall that turned out to be a free fix (EV run 2026-10-31, 2026-11-02).

**Checking:** dealer VIN printout of open campaigns > brand VIN checker (**with control lookups**: VIN ±1 digit, a fake VIN, a known-positive VIN; one brand checker answered "not affected" even for a fake VIN) > national DB by VIN > model-level DBs (KBA Rückrufdatenbank, EU Safety Gate, NHTSA for the same hardware). A brand checker may say "a recall is open" without naming it; ask the dealer for the campaign code. See [vin-sources.md](vin-sources.md).

---

## 2. Manufacturer warranty: the country rule

| Rule | Tag |
|---|---|
| A car first sold in country X is covered by the brand network in country Y, but the brand "may legitimately apply the terms of the original warranty" and is under no obligation to apply Y's better terms. A DE-sold Hyundai keeps DE's 5 years, not PT's 7. | V (EC FAQ Q5) |
| Servicing at an independent garage does **not** void the warranty. The brand may refuse a claim only if the failure is causally linked to a non-OE part. Basis: MVBER 461/2010 + Supplementary Guidelines, extended by Reg. 2023/822 to 31 May 2028. | V |
| Exception: **voluntary extension/goodwill programmes may require network servicing** (Toyota Relax, Peugeot Allure Care/Peugeot Care). | V (brand T&Cs) |
| Manufacturer warranties are vehicle-bound and pass to the next owner, given proof of the service schedule. Get the **digital service record printed** by a dealer; many brands keep it online only. | V for Kia; A as a general rule |
| Warranty start = handover/first registration as the brand recorded it, which can differ from the registration date in the documents. Ask the brand for the end dates by VIN; don't compute them. | V (EV run 2026-11-04: brand's battery-warranty end date implied a start ~1 month after first registration) |
| Brand programmes tied to a country list (e.g. Peugeot Allure Care: the car must stay registered in a listed country). | V (PT T&Cs via snippet) |

### Typical warranty lengths by brand (dated: ADAC 7/2025 for DE; PT where known)

The vehicle warranty and the HV-battery warranty are separate. "Status" = a DE-sold 2023–24 car in late 2026.

| Brand | DE vehicle warranty | PT | Status late 2026 | Tag |
|---|---|---|---|---|
| VW, Škoda, Audi | 2 yr, no km cap | brand term not confirmed (importer guide: 2 yr) | **Expired** unless an Anschlussgarantie was bought with the new car (up to 5 yr/150k total; transfers; does **not** extend the HV battery) | V (DE) |
| Cupra | 5 yr / 150k (first 2 yr no km cap), first buyer, cars ordered for DE from 21 Dec 2023 (UK: registered from 3 Apr 2024) | not confirmed | Valid to ~2029 if eligible; 2nd-owner transfer **unconfirmed** ("Erstkäufer" wording) | V (DE brochure) |
| Mercedes | 2 yr, no km cap | ~2 yr; one PT complaint says the PT network refused a DE warranty claim, so confirm first | Expired | V (DE) / A (PT) |
| BMW / MINI | no manufacturer warranty; 3-yr extended dealer liability | MINI PT: 3 yr, no km cap | 2023 expired; 2024 to ~2027. Whether PT dealers honour a DE dealer's extended liability: unconfirmed | V / A |
| Hyundai | up to 5 yr, no km cap (model-dependent) | 7 yr, no km cap | DE car: ~2028–29 | V |
| Kia | 7 yr / 150k | 7 yr / 150k | to ~2030–31 (12 V battery 2 yr, infotainment 3 yr) | V |
| Nissan | 3 yr / 100k | not confirmed | 2023 expired; 2024 to ~2027 | V (DE) |
| Toyota | 3 yr / 100k + **Relax** (renews with each network service, up to 10 yr) | Relax up to 10 yr / 200k km (last activation <185k) | Alive only if the service chain is unbroken; see §4 | V (PT T&Cs) |
| Subaru | 5 yr / 160k | not confirmed | to ~2027–29 | V (DE) |
| Peugeot | 2 yr | up to 8 yr / 160k via Allure Care / Peugeot Care (renewing) | Base expired; extension only if conditions met | V / A |

### HV-battery warranty

| Fact | Tag |
|---|---|
| Almost every brand: **8 yr / 160,000 km, ≥70 % capacity**, from first registration, transfers with the car, claimable at any EEA dealer. Kia: sources conflict (7/150k vs 8/160k). VW states 78 % at 3 yr/60k and 74 % at 5 yr/100k on newer cars (check build date). | V (secondary for some brands) |
| Toyota: 8/160k base; with a passed **yearly BEV health check** at a Toyota dealer, ≥70 % to 10 yr; functional defects up to 10 yr / 1,000,000 km. A missed check loses the extension. | V (toyota.pt FAQ) |
| Conditions that void it: deep discharge / left at 0 % >14 days (BMW, Nissan), chip tuning (Mercedes), not following the service schedule. | V / A |
| **What it does NOT cover:** it is the cells and pack only. Audi's list is "exclusively" cell modules, housing, cooling elements, module connectors. **Not covered:** onboard charger (OBC), DC-DC converter (incl. combined units like Hyundai/Kia ICCU or VW "OCDC"), drive motor, inverter, heat pump, 12 V battery, charging cables. Those fall under the normal vehicle warranty, then self-insured. | V (Audi Garantie 11/2024, VW terms) |

WHY this matters: a typical out-of-warranty OBC/DC-DC repair is ~€1.5–3.5k, a heat-pump compressor ~€2k, so on a 2-yr-warranty brand the money risk sits in these parts, not in the pack (EV run 2026-10-31; prices A).

---

## 3. Goodwill and extension programmes

| Rule | Tag |
|---|---|
| A recall is an EU-wide obligation. A goodwill or extension programme is a **voluntary, national** offer by the brand's importer. **Count it only when you have it in writing for that VIN** (email from the brand's customer service in the buyer's country, or a dealer warranty printout). | V (rule) |
| Example: Hyundai/Kia ICCU extension 15 yr / 300k km (pre-mid-2024 builds) was announced country by country — FI, then DE (Apr 2026), DK — with "other markets expected"; PT was unconfirmed in Oct 2026. For an imported car also ask whether the origin-country extension is honoured in the buyer country. | V (FI/DK/DE) / A (PT) |
| Kulanz / goodwill case by case: discretionary per importer, often a % of cost, depends on age, km and network service history (owner reports: 50–90 %). Never count it. | A |
| Battery-swap programmes run as official **recalls** (e.g. Mercedes EQA/EQB) are recalls: free, VIN-bound, EU-wide (§1). | V |

---

## 4. Extension-by-service schemes (Toyota Relax type)

Some brands extend the warranty by 12 months / 15k km at **each scheduled service at an authorised workshop** (Toyota Relax: up to 10 yr / 200k km; Toyota battery: yearly BEV check; Peugeot Allure/Care: network servicing after the base warranty).

| Fact (Toyota Relax PT T&Cs, read 2026-11-02) | Tag |
|---|---|
| Follows the car whoever owns it; any official brand workshop in PT or EU activates it; a car sold new by any official European Toyota entity is eligible (only cars not sold by them are excluded). | V |
| A lapsed cover restarts 30 days after the next service. | V |
| Excluded: hire/taxi/ride-hailing use, parts covered by recalls, EV charging cables, **traction battery cells** (those have their own battery warranty, §2). | V |
| A battery health check done at a dealer counted as the activating service for an imported car: the brand's system showed Relax active for 12 months / +15k km from that check date. | V (EV run 2026-11-04, brand email) |

**How to verify for one VIN (in this order):**
1. Ask the seller for the service history and every health-check printout; check the interval chain is unbroken (≤12 months / ≤15k km between services).
2. Online eligibility simulator, if the brand has one — **with a control**. Toyota PT's public simulator page sends `makeFullValidations=false` and so tells *every* plate "eligible"; only the full-validation mode (same API, `=true`, needs the page's own token, so call it from inside the page) gave real answers, and a known PT-sold control plate had to pass for the result to mean anything. WHY: the default "eligible" was a generic message (EV run 2026-11-02).
3. A written answer from the brand (see §7) with the end date and km cap for that VIN. That is the only result to count.

---

## 5. Seller's statutory liability (EU consumer law)

### EU baseline
| Rule | Tag |
|---|---|
| A **dealer** selling to a consumer is liable for lack of conformity for **2 years**. For used goods this may be cut to **≥1 year** by agreement, clearly disclosed. Many countries go further (PT: 3 yr). | V (Your Europe) / I (Dir. 2019/771 art. 10) |
| Burden of proof: a defect appearing within the presumption period (≥1 year; some countries 2) is presumed present at delivery; the seller must disprove it. Not for normal wear. | V (DE/PT statutes) / I (EU minimum) |
| **Private sale** (consumer → consumer): no consumer-law liability; usually sold as-is. Only national civil-code hidden-defect rules remain, and the buyer must prove the defect predates the sale. | V (PT) / I (other countries) |
| Signing as a business ("Export / Gewerbe / ohne Gewährleistung" contracts) waives consumer protection. If you are in fact a consumer and the dealer knows it, the exclusion is void, but don't rely on that. | A |
| Distance purchase (contract signed online/by email, car delivered or collected) gives a **14-day withdrawal right** (Consumer Rights Directive). See [buy/deposit-payment.md](buy/deposit-payment.md). | V (DE §312g BGB) |
| Cross-border: if the foreign dealer **directs its business to the buyer's country** (buyer-language site, delivery there, ads on the buyer's national portal), its choice of law can't remove the buyer-country's mandatory protection (Rome I art. 6). If you walk into a dealer that doesn't target your country, its law applies. | V (principle; per case) |
| Enforcing from abroad is slow: European Small Claims (≤ €5,000, written), free help from the ECC network (e.g. CEC Portugal ↔ EVZ Germany). Suing at home only if the dealer directed activity to your country (Brussels Ia art. 17–18). | A |

### DE dealer (BGB, since 2022)
- **§476(2):** used-car liability can be cut from 2 years to **1 year** only if the consumer is specifically told **before** contracting and it is **expressly and separately agreed** (a separate tick box or signature, not small print). Push for 2 years. **V**
- **§476(1):** core defect rights can't be excluded against a consumer. Agreeing a worse condition than normal for such a car needs specific notice plus a separate agreement. **V**
- **§477:** for **1 year** after handover any defect is presumed to have existed at handover. **V**
- Writing an inspection report into the order ("condition as per report X") makes everything recorded as OK an agreed condition: it helps the buyer. Read the report before signing. **I** (EV run 2026-11-06)
- Dealer terms may require repairs at the dealer's premises or with its prior consent; from abroad that makes the second year of liability worth little. **V** (dealer AGB read 2026-11-06)

### PT dealer (DL 84/2021, in force 1 Jan 2022) — PT only
- Guarantee **3 years** from delivery (art. 12 n.º 1); for used goods reducible to **18 months by express agreement** (art. 12 n.º 3). **V**
- Presumption: 2 years; **1 year for used goods** (art. 13 n.º 3). The buyer must first show an actual defect. **V**
- Remedies (art. 15): repair or replacement, then price reduction or termination. Commonly reported but not checked against the statute: 30-day rejection right, +6 months guarantee per repair (max 4), direct claim against the producer. **A**
- Applies to an imported car sold by a PT dealer, whatever its origin. **A** (follows from scope)
- Disputes: consumer arbitration (CNIACC / regional centres) is cheap and mandatory for the trader up to €5,000 if the consumer chooses it (Lei 63/2019). **A**
- Private sale in PT: Código Civil art. 913 ff.: report the defect within **30 days of discovery and 6 months of delivery** (art. 916); court action lapses 6 months after the report (art. 917). **V** (30 days + action; the 6-months-from-delivery limb is our reading, **I**)

**Ranking for the buyer (I):** buyer-country dealer (longest term, local arbitration) > foreign dealer (typically 1 year, hard to enforce) > private seller (hidden defects only).

---

## 6. Used-car guarantees ("Garantie", "certified used", warranty insurance)

These are **contracts or insurance products**, not the statutory liability (§5) and not the manufacturer warranty (§2). They add to the statutory liability; they never replace it.

| Check | Why / tag |
|---|---|
| Get the **written terms**: issuer (brand, dealer, or an insurer behind it), term, km cap, excess, component list. A dealer cover page that names a "Gebrauchtwagengarantie" with no provider or term is not a guarantee yet. | EV run 2026-11-06: certified-used order named the product, gave no terms. V |
| **Is the HV system covered** (OBC, DC-DC, motor, inverter, heat pump)? Many lists stop at mechanical parts. | I |
| **Valid in the buyer's country?** Ask the issuer in writing whether a workshop there can claim it. DE brand products (VW "Garantieverlängerung", "Gebrauchtwagengarantie", 24–96-month cars, ≤150k km, excess €0–500, transferable to private buyers) are DE products; PT validity was unconfirmed. | A |
| **Transferable** to the next owner? Some are first-buyer only. | V (varies) |
| Warranty-insurance top-ups bundled with a brand warranty (e.g. a 3-yr insurance extension on DE-sold Hyundai Kona after the 5-yr warranty, reduced scope) count only if transferable and valid in the buyer country in writing. | V (DE press) / A (PT) |
| Accepting a 1-year statutory term from a foreign dealer is reasonable **only** together with a written brand used-car guarantee (≥12 months, claimable at brand partners in the buyer's country). From abroad that guarantee is worth more than a second year of claims against the dealer. | I (EV run 2026-11-06) |

---

## 7. How to ask the brand (warranty end dates, extension status, recall details)

**Channel order** (best first):
1. **Brand web contact form** (creates a ticket, can route to a chosen dealer).
2. **Phone** — the owner calls with the VIN; ~1 minute.
3. **Photo from the seller** of the brand app's warranty/service screen (e.g. "MyToyota → Garantia") and the service book. Often the fastest evidence; costs no brand contact.
4. **Brand customer-service email** — answered a non-owner in ~48 h with exact end dates (date + km cap) for warranty and battery (EV run 2026-11-04). If the address isn't on the contact page, look in the site's structured data (JSON-LD `contactPoint`).
5. **Dealer generic inboxes ("geral@", "info@")** last: no reply, no auto-ack in 48 h (EV run 2026-11-02 → 11-04). Prefer a direct after-sales address if the dealer site lists one.

**Rules:**
- **Owner approval first** for any outbound brand/dealer message (draft → owner OKs the exact text → send). Vet agents never message sellers; seller asks go through `carhunt evidence` (outreach agent sends).
- **Cap: 2 emails** (brand + one dealer) **+ 1 follow-up** after 24 h, threaded into the original. Anything more needs the owner's OK. WHY: inbox noise, and phone/form are faster anyway (EV run 2026-11-03).
- Short, polite, in the brand country's language; VIN only; no seller name, no price, no personal data beyond name and email.
- Ask concrete questions: (a) vehicle warranty / extension active, end date and km cap; (b) battery warranty end date and whether the extension is active; (c) does it continue after an owner change and an import (state the first-sale country); (d) which campaign is open and is it done.
- For recalls, **quote the checker's exact message** or attach a screenshot. WHY: "which recall is open?" alone was not understood by the brand's support (EV run 2026-11-04).
- Treat a written answer naming the VIN as **V** for that car; anything verbal or "the dealer said" as **A** until written.
