# Import guides: bring a car bought abroad home and register it

No guides ship with the repo: write the ones for your destination with the template below. `carhunt doctor` warns while the destination file is missing.

## How it works

Every cross-border purchase has two halves, kept in separate files in this folder:

| Half | File | Answers |
|---|---|---|
| Destination side | `<dest>-registration.md` (e.g. `pt-registration.md`) | Order of steps at home, deadlines, taxes, fees, which originals the registry keeps, how long the transit cover must last |
| Seller-country side | `<seller>-to-<dest>.md` (e.g. `de-to-pt.md`) | Documents to collect, who de-registers and when, transit plate + insurance, costs, days, ownership traps, buyer step list |

- Config `vet.destination_country` (e.g. `PT`) selects the destination file. The seller-country file is `<seller-country lowercase>-to-<dest lowercase>.md`; a country without its own file falls back to `other-to-<dest>.md`.
- Agents read **both** files before a deal: the destination file sets how long the transit plate/insurance must run; the seller file says how to get it.
- Contract, deposit and pickup rules: [../buy/contract-checklist.md](../buy/contract-checklist.md), [../buy/deposit-payment.md](../buy/deposit-payment.md), [../buy/pickup-day.md](../buy/pickup-day.md).

## Rules for any seller country

- **Originals or nothing:** the destination registry needs the original foreign registration document(s) and the CoC. Never accept a copy or "I'll post it later".
- **The contract/invoice names the buyer** (full name exactly as on the ID, address with postcode and country): it is the registration upload at home and the transit-plate application abroad.
- **New-vehicle VAT:** check registration field B on any car under a year old; a car that counts as "new" under EU VAT rules owes VAT in the destination even from a private seller.
- **Seller ≠ owner** (lease, finance, company car): run the seller-country check in [../buy/deposit-payment.md](../buy/deposit-payment.md) §6.

## Writing a destination guide

1. Create `<dest>-registration.md` with these sections:
   - Order of steps (state which step assigns the plate number — this decides the transit window).
   - Deadlines (entry → customs/tax declaration; original-document deposit).
   - How long the transit plate + insurance must cover (drive + any step that needs the car present).
   - VAT at entry (new-vehicle case), registration tax, annual tax — per powertrain.
   - Documents: the originals list and which ones the registry keeps.
   - Fees, days per step, total DIY vs agent.
   - DIY vs agent (what an agent can and cannot do), accounts/logins needed.
   - Insurance gap, tyre/CoC rules at registration, open questions.
   - Buyer step list.
2. Create `<seller>-to-<dest>.md` per seller country (documents, de-registration, transit plate + insurance, office hours/appointments, costs and days, ownership checks, buyer step list), plus `other-to-<dest>.md` for the rest.
3. Link primary sources (registry, tax authority, law text) next to each rule.
4. Set `vet.destination_country` in the config.
