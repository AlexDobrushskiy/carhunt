# Deposit & payment

> Snapshot: researched Oct–Nov 2026 (EV run). Prices, laws and tool behaviour drift — re-check anything you act on.

Tags: **V** verified from a primary/official source · **A** anecdotal/forum/secondary · **I** inferred.
Siblings: [contract-checklist.md](contract-checklist.md) · [pickup-day.md](pickup-day.md) · [doc-verify.md](doc-verify.md) · [../coverage-rules.md](../coverage-rules.md)

## 1. Standing line

- Agents answer any payment question with: **"I pay at handover by instant transfer; no deposit before."** No escalation needed for that line.
- A seller who **insists on a deposit** → escalate to the owner (money is owner-only). Agents never name amounts, never pay.
- Don't offer bank-app screenshots as proof of funds: it exposes finances and buys nothing (EV run 2026-11-02).
- WHY: the line was approved twice and then made standing (EV run 2026-11-02/03).

## 2. If the owner agrees to a deposit

Only all of these:
1. **Verified dealer** (§3). Never a deposit to a private seller you haven't met (**I**).
2. **Signed order with the VIN first** ([contract-checklist.md](contract-checklist.md)); deposit written in it: amount, credited to the price, refunded in full on withdrawal, on deviation from the agreed description, and on non-delivery.
3. **SEPA transfer to a domestic IBAN held by the contract seller** (same legal entity as on the order), or card at the dealership if offered (chargeback).
4. **IBAN read back by phone** on a number taken from the dealer's **own website** — not from the email, not from the ad (portal numbers are often call-tracking numbers, fine for calls, useless for verification).
5. Small: ~1–2 % of price is normal (**A**). No statutory size in DE.

DE law on deposits (consumer from dealer), all **V** (BGB, gesetze-im-internet) unless tagged:
- A deposit (Anzahlung) is part payment; if no contract results, it is repaid.
- Distance-sale withdrawal → full refund incl. deposit within 14 days (§357); the dealer may hold it until the car is back. Value loss (§357a) only for use beyond testing.
- Car deviates from the description (§434) → refuse delivery or demand cure then rescind (§§437/439/440/323): full refund.
- Dealer sells to someone else after accepting → deposit back (§326(4)) + damages (§§280/283) or wasted costs, e.g. flights (§284); the dealer can't keep the deposit by set-off (BGH VIII ZR 318/19).
- **Non-refundable "reservation fee"** in standard terms: very likely void (analogy to BGH I ZR 113/22, **I**). Refundable reservation credited to the price: fine.
- BE: write *acompte* (binding sale) or *arrhes* (either side may withdraw: buyer loses it, seller repays double) explicitly (**A**, forum; new Civil Code Book 7 unchecked).

## 3. Dealer identity checks (before any money or signature)

| Check | How | Pass |
|---|---|---|
| Company register | National register (DE Handelsregister / northdata; others: national business registry) | Entity active; name matches order + Impressum |
| VAT ID | EU **VIES** | Valid, name matches |
| Impressum / legal notice | Dealer's own site + portal Impressum + email signature | All three name the same entity/address |
| Second entity | Signature/Impressum says "sells for X **or** Y" | Order must name one; IBAN holder must equal it |
| Salesperson | Dealer's own team page | Same name, extension, email |
| Domain | Age (WHOIS / first seen), **lookalike domains** (typo, extra hyphen, other TLD) | Old domain, no live lookalikes |
| Email headers | Gmail "Show original" (read-only): **SPF / DKIM / DMARC = pass** for the dealer domain; **no Reply-To** to another domain; sending infrastructure plausible (e.g. the group's M365 tenant) | All pass, no Reply-To |
| DMARC policy | `dig TXT _dmarc.<domain>` | **p=none** → forged mail from that domain is *not* rejected → phone-verify **any** bank-detail email |
| Official phone | From the dealer's own website (not the email, not the ad) | Use for IBAN read-back |
| IBAN | Usually not published | Phone read-back only |
| Reputation | Portal dealer ratings, search "<dealer> Betrug/scam" | No scam reports |

WHY: one run verified a dealer this way in one pass — all mail passed SPF/DKIM/DMARC but the domain had DMARC p=none, and the dealer sold for two entities (EV run 2026-11-06).

## 4. Paying the balance

- **SEPA Instant at the car**, during the handover sitting. **Papers and keys change hands in the same sitting** as the payment.
- **Verification of Payee (VoP)** — mandatory for euro credit transfers in the EU since **9 Oct 2025** (**V**, EU Instant Payments Regulation; bank pages): type the payee's **exact legal name**.
  - *Match* → go.
  - *Close match* → only if the suggested name is the contract seller's legal name.
  - *No match / check not possible* → **stop**, call the official number.
  - VoP checks the name on the IBAN, **not who owns the car** (§6).
- **Check your own instant-transfer limit** before travelling (banking apps cap per transaction/day). If too low: raise it, or send the balance 1–2 days before pickup after the phone check — acceptable only with a signed order + withdrawal right (DE distance sale) (**I**).
- Get in exchange: VAT invoice (dealer VAT is final for a private buyer — no refund, no second VAT unless "new means of transport", see [../import/README.md](../import/README.md)), deposit receipt, originals listed in [pickup-day.md](pickup-day.md).

**Never:**
- Escrow/"Treuhand" services — a classic scam vehicle, unnecessary with a real dealer (**A**, ADAC). (BE: AutoScout24's 2019 Digitrust escrow partner — not confirmed active in 2026.)
- Payment links, or bank details sent only by email/PDF without phone check.
- A private or foreign IBAN for a domestic dealer.
- Cash ≥ €10k: DE has no cap until 2027 but ≥€10k triggers ID checks (GwG §10(6a), **V**) and it's a theft risk. BE: €3,000 cash limit for payments to traders; private→private no limit (**A**, law text not read).

## 5. Scam patterns

| Pattern | Tell | Response |
|---|---|---|
| Car "stored abroad" | Price well under market; seller "relocated"; car in another country | Walk unless you can see it |
| Upfront % to foreign IBAN | 30–50 % "deposit" before viewing | Never |
| "Delivery by transport company" | You never meet the seller; fake shipper site | Never |
| Escrow/Treuhand suggestion | Seller proposes the escrow service and sends its link | Never |
| Bank-detail change by email | "Our account changed" | Phone-verify on the website number |
| Fake transfer screenshot | (Against sellers) a "paid" screenshot | Seller side only — note it when you sell your old car |
| Too cheap on thin comparables | Price far below a median of few comps | Treat as scam-level until papers, SoH and who-is-selling check out |

WHY: one leboncoin listing was a textbook deposit scam (car "stored in Germany", 30 % transfer, a relay contact) (EV run 2026-11-04); BE 2dehands fake ads asking half upfront to a foreign IBAN with transport delivery (**V**, VRT 2024/2026).

**Sellers fear scams too.** Disarming line: *"I ask for nothing — no links, no payments, no codes. I'll come in person."* A private seller who had asked "how do I know you're not a phisher?" answered "come and see it any time" within 2 minutes (EV run 2026-11-06).

## 6. Seller ≠ owner (top private-sale trap)

Seller's ID must match the keeper/owner on the papers. Per country:

| Country | Check | Red flag |
|---|---|---|
| DE | **Original ZB II** (title) in the seller's hands; field (1) gives no. of previous keepers | No original ZB II = likely bank lien; buying without checking it counts as gross negligence (no good-faith acquisition) (**A**) |
| FR | Carte grise **C.1** names the seller | C.1 names a lessor (LOA/LLD) → buy from the lessor or walk (**A**) |
| ES | Ask for proof of no *reserva de dominio* (finance retention of title) | Retention of title recorded → seller can't transfer (**A**) |
| BE | The **CIM is not proof of ownership** (**V**, mobilit). Ask for the original purchase invoice in the seller's name, a lender's payoff/release letter if financed, C.1 matching the seller's ID. Pledge register needs a BE eID — seller can search and show it (incomplete) | C.1 = lessor/employer, or "Pro Business" trim (BE fleet spec) → company/lease car: buy from the lessor or walk (**A**) |
| NL | RDW open data by plate (free): owner type timeline via Finnik | Ownership type mismatch (**A**) |

Dealer sales: ex-lease cars are fine — the dealer bought them; the ZB II original is handed over at pickup ([pickup-day.md](pickup-day.md)).
