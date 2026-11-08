# Deposit & payment

Siblings: [contract-checklist.md](contract-checklist.md) · [pickup-day.md](pickup-day.md) · [doc-verify.md](doc-verify.md)

## 1. Standing line

- Agents answer any payment question with: **"I pay at handover by instant transfer; no deposit before."** No escalation needed for that line.
- A seller who **insists on a deposit** → escalate to the owner (money is owner-only). Agents never name amounts, never pay.
- Don't offer bank-app screenshots as proof of funds: it exposes finances and buys nothing.

## 2. If the owner agrees to a deposit

Only all of these:
1. **Verified dealer** (§3). Never a deposit to a private seller you haven't met.
2. **Signed order with the VIN first** ([contract-checklist.md](contract-checklist.md)); deposit written in it: amount, credited to the price, refunded in full on withdrawal, on deviation from the agreed description, and on non-delivery.
3. **SEPA transfer to a domestic IBAN held by the contract seller** (same legal entity as on the order), or card at the dealership if offered (chargeback).
4. **IBAN read back by phone** on a number taken from the dealer's **own website** — not from the email, not from the ad (portal numbers are often call-tracking numbers, fine for calls, useless for verification).
5. Small: ~1–2 % of the price.

A non-refundable "reservation fee" in standard terms: ask to strike. BE: write *acompte* (binding sale) or *arrhes* (either side may withdraw) explicitly.

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

## 4. Paying the balance

- **SEPA Instant at the car**, during the handover sitting. **Papers and keys change hands in the same sitting** as the payment.
- **Verification of Payee (VoP)** on the euro transfer: type the payee's **exact legal name**.
  - *Match* → go.
  - *Close match* → only if the suggested name is the contract seller's legal name.
  - *No match / check not possible* → **stop**, call the official number.
  - VoP checks the name on the IBAN, **not who owns the car** (§6).
- **Check your own instant-transfer limit** before travelling (banking apps cap per transaction/day). If too low: raise it, or send the balance 1–2 days before pickup after the phone check — only with a signed order + withdrawal right (DE distance sale).
- Get in exchange: VAT invoice, deposit receipt, originals listed in [pickup-day.md](pickup-day.md).

**Never:**
- Escrow/"Treuhand" services — a classic scam vehicle, unnecessary with a real dealer.
- Payment links, or bank details sent only by email/PDF without phone check.
- A private or foreign IBAN for a domestic dealer.
- Large cash payments (ID checks, national cash limits, theft risk).

## 5. Scam patterns

| Pattern | Tell | Response |
|---|---|---|
| Car "stored abroad" | Price well under market; seller "relocated"; car in another country | Walk unless you can see it |
| Upfront % to foreign IBAN | 30–50 % "deposit" before viewing | Never |
| "Delivery by transport company" | You never meet the seller; fake shipper site | Never |
| Escrow/Treuhand suggestion | Seller proposes the escrow service and sends its link | Never |
| Bank-detail change by email | "Our account changed" | Phone-verify on the website number |
| Too cheap on thin comparables | Price far below a median of few comps | Treat as scam-level until papers, SoH and who-is-selling check out |

**Sellers fear scams too.** Disarming line: *"I ask for nothing — no links, no payments, no codes. I'll come in person."*

## 6. Seller ≠ owner (top private-sale trap)

Seller's ID must match the keeper/owner on the papers. Per country:

| Country | Check | Red flag |
|---|---|---|
| DE | **Original ZB II** (title) in the seller's hands; field (1) gives no. of previous keepers | No original ZB II = likely bank lien |
| FR | Carte grise **C.1** names the seller | C.1 names a lessor (LOA/LLD) → buy from the lessor or walk |
| ES | Ask for proof of no *reserva de dominio* (finance retention of title) | Retention of title recorded → seller can't transfer |
| BE | The registration certificate is not proof of ownership. Ask for the original purchase invoice in the seller's name, a lender's payoff/release letter if financed, C.1 matching the seller's ID. Pledge register needs a BE eID — seller can search and show it (incomplete) | C.1 = lessor/employer, or "Pro Business" trim (BE fleet spec) → company/lease car: buy from the lessor or walk |
| NL | RDW open data by plate (free): owner type timeline via Finnik | Ownership type mismatch |

Dealer sales: ex-lease cars are fine — the dealer bought them; the ZB II original is handed over at pickup ([pickup-day.md](pickup-day.md)).
