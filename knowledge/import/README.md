# Import module: bring a car bought abroad home and register it

> Snapshot: researched Oct–Nov 2026. Prices, laws and tool behaviour drift — re-check anything you act on.

Tags: **V** = verified from a primary/official source · **A** = anecdotal/forum/secondary · **I** = inferred.

## How it works

Every cross-border purchase has two halves, kept in separate files:

| Half | File | Answers |
|---|---|---|
| Destination side | `<dest>-registration.md` (e.g. [pt-registration.md](pt-registration.md)) | Order of steps at home, deadlines, taxes, fees, which originals the registry keeps, how long the transit cover must last |
| Seller-country side | `<seller>-to-<dest>.md` (e.g. [de-to-pt.md](de-to-pt.md)) | Documents to collect, who de-registers and when, transit plate + insurance, costs, days, country-specific ownership/scam traps, buyer step list |

- Config `vet.destination_country` (e.g. `PT`) selects the destination file. The seller-country file is `<seller-country lowercase>-to-<dest lowercase>.md`; anything without its own file falls back to `other-to-<dest>.md`.
- Agents read **both** files before a deal: the destination file sets how long the transit plate/insurance must run; the seller file says how to get it.
- Brand warranty, recall and consumer-law rules live in [../coverage-rules.md](../coverage-rules.md); contract, deposit and pickup rules in [../buy/contract-checklist.md](../buy/contract-checklist.md), [../buy/deposit-payment.md](../buy/deposit-payment.md), [../buy/pickup-day.md](../buy/pickup-day.md).

## What exists

| Seller country ↓ / destination → | PT |
|---|---|
| DE | [de-to-pt.md](de-to-pt.md) — in depth |
| FR | [fr-to-pt.md](fr-to-pt.md) — in depth |
| ES | [es-to-pt.md](es-to-pt.md) — in depth |
| BE | [be-to-pt.md](be-to-pt.md) — in depth |
| LU, NL, IT, others | [other-to-pt.md](other-to-pt.md) — short |
| Destination rules | [pt-registration.md](pt-registration.md) |

No other destination exists yet.

## Universal EU rules (any seller country → any EU destination)

- **VAT, new means of transport:** a car supplied **≤6 months after first entry into service OR with ≤6,000 km** is "new" and VAT is due in the **destination** country, even from a private seller. To count as used it must exceed **both** thresholds. Check field B (first registration) on any car under a year old. **V** (Your Europe; PT RITI art. 6; BE Code TVA art. 8bis).
- **VAT, used car:** private seller → no VAT anywhere. Dealer/company seller → the seller-country VAT (regular or margin scheme) is **final** for a private buyer: no refund, no second VAT at home. VAT-exempt intra-EU supply needs a buyer VAT ID; "net export" prices are for businesses only. **V** (Your Europe; EC Taxation).
- **I:** if a company seller arranges the transport to the destination, the sale may become an EU distance sale taxed at the destination rate. Collect it yourself or truck it on your own contract.
- **Originals or nothing:** the destination registry needs the **original** foreign registration document(s) plus the CoC. Never accept a copy or "I'll post it later". **V** for PT (CISV art. 20(5)); **A** for the general claim.
- **The contract/invoice must name the buyer** (full name exactly as on the ID, address incl. postcode and country). It is the customs/registration upload at home and the transit-plate application abroad.
- **The new state withdraws the old registration** (Dir. 1999/37 art. 5). **V**
- **Transit insurance by destination insurer:** Motor Insurance Directive 2009/103 art. 15 (as amended by 2021/2118) lets the risk sit in the destination state for **30 days from acceptance of delivery**, before registration. **V** for the law; whether an insurer actually sells it is country-specific and often unverified.
- **Warranty** follows the VIN EU-wide but on the **origin country's terms** (EU Commission motor-vehicle FAQ Q5) → [../coverage-rules.md](../coverage-rules.md). **V**
- **Payment:** SEPA Instant at the car with Verification of Payee (mandatory since 9 Oct 2025, Reg. 2024/886); "no match" = stop. → [../buy/deposit-payment.md](../buy/deposit-payment.md). **V**
- **Seller ≠ owner** (lease, finance, company car) is the top private-sale trap in every country; each seller file lists the local check.

## Adding a destination country

1. Create `<dest>-registration.md` with these sections (copy [pt-registration.md](pt-registration.md)):
   - Order of steps (state which step assigns the plate number — this decides the transit window).
   - Deadlines (entry → customs/tax declaration; original-document deposit).
   - How long the transit plate + insurance must cover (drive + any step that needs the car present).
   - VAT rules at entry (new-vehicle case), registration tax, annual tax — per powertrain.
   - Documents: the originals list and which ones the registry keeps.
   - Fees table with the date read; days per step; total DIY vs agent.
   - DIY vs agent (what an agent can and cannot do), accounts/logins needed.
   - Insurance gap, tyre/CoC rules at registration, open questions.
2. Create `<seller>-to-<dest>.md` for each seller country, or reuse the seller-side facts from the existing `*-to-pt.md` files (they are mostly destination-independent) and change only the "covers the destination steps?" parts.
3. Cite primary sources (official registry, tax authority, law text) with links; tag every legal/coverage claim **V/A/I**; put the dated snapshot banner on top; add a row to the matrix above.
4. Update `vet.destination_country` in the config.
