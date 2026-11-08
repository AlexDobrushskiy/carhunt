# Contract checklist (purchase order / Kaufvertrag review)

Siblings: [deposit-payment.md](deposit-payment.md) · [pickup-day.md](pickup-day.md) · [doc-verify.md](doc-verify.md) · [shutdown.md](shutdown.md) · [../import/README.md](../import/README.md)

## 1. How to review

- **Read every page yourself** (OCR/vision if scanned), never another agent's summary. The errors that matter (name, postcode, pre-ticked boxes) sit on pages a summary skips.
- **Identify which file is signed and returned.** Dealers often send a full copy for reading and a separate "zu unterzeichnende Dokumente" file; only the latter goes back.
- Grade every item **✅ OK · ⚠️ missing/unclear · ❌ problem**, each with the **exact quoted contract text** and page. No paraphrase.
- Each ⚠️/❌ gets a one-line ask in **the seller's language + English** (DE/EN templates in §4).
- **List every signature field** (page, field label, mandatory vs optional). Mark optional ones (marketing consent → tick "Nein"/skip) and conditional ones (a §476 side agreement is signed only if you accept it).
- Verdict: **sign as is / sign after fixes / don't sign.**
- **Re-diff every revised version** against the previous one, page by page (text diff of all pages + any .docx). Report: what you asked for and got, what changed unasked, page reorderings, dates.
- Personal data (contract PDFs, IDs, signatures, signed scans) stays **in the agent scratchpad only** — never the repo, notes, or cardb. cardb gets only the verdict line (`cardb event CAR --type contract --summary "v2: OK to sign"`).
- Review agents are read-only: never reply to the seller, never sign, never pay. The owner signs and sends.

## 2. Red-flag table

| Field | What must be there | Why |
|---|---|---|
| Buyer name | Exactly as on the buyer's ID document (spelling, transliteration) — the same ID used for export plates/import | Export plates are issued against the ID; the destination customs/import filing matches invoice ↔ ID |
| Buyer address | Full street, **full postcode, country** | Drafts often carry a wrong postcode and no country; dealer systems may not accept foreign postcode formats — a correct handwritten postcode is OK |
| Seller legal entity | One named legal entity; **must equal the IBAN holder** (see [deposit-payment.md](deposit-payment.md)) | Dealer groups sell for 2+ entities; a template page may name another one (harmless if only boilerplate) |
| Car identity | VIN, model/variant, first registration, km at signing | Ties the contract to the car you vetted ([doc-verify.md](doc-verify.md)) |
| Price | Gross incl. VAT, VAT shown; "Nebenleistungen/extras €0" or each fee itemised with its amount (transfer, registration, export plates, admin, insurance) | Fees appear late otherwise |
| Deposit | Amount, credited to price, refund terms (withdrawal, deviation, non-delivery). "€0 at order, full at handover" is ideal | See [deposit-payment.md](deposit-payment.md) |
| Included items | Number of keys, CoC, both registration parts (DE: ZB I + ZB II) **originals**, charging cable(s), second wheel set (if agreed), service proof (digital/printout) | Drafts omit keys and papers; don't assume an item is included unless listed |
| Condition reference | "Zustand/Lieferumfang laut <inspection report no., date>" + "unfallfrei" + list of fixed defects | Writing the report in turns everything it lists as OK into a promise |
| Liability (DE) | Statutory 2 years, or a 1-year cut you **knowingly** accepted (§476 side agreement) | See §3 |
| Guarantee | If a used-car guarantee is advertised: provider, term, coverage (HV system?), **valid in the buyer's country**, in writing | Packs may name a "certified used car" programme with no terms anywhere |
| Recalls/campaigns | Written confirmation that open campaigns are done before handover | Easier before export |
| Delivery | (Non-binding) delivery date, pickup window long enough for travel (DE default 8 days after ready notice) | |
| Payment | Due date + method (transfer at handover) | |
| Export/plates | Who gets export plates + insurance, cost, who deregisters | Seller-country import guide ([../import/README.md](../import/README.md)) |
| Place of signing | Buyer's city, not the dealer's | §3 |
| Acceptance | Written order confirmation from the dealer | DE dealer terms: your signed order is only an offer until confirmed in text form or delivered |
| Final invoice | Buyer's name, address **with country** | Needed for the destination import filing |
| Withdrawal notice | Correct distance-sale notice, model form attached, period runs from taking possession | §3 |

## 3. DE dealer specifics (consumer buying from a German dealer)

- **Sign remotely, view at pickup.** An order concluded by email/e-sign is a distance contract with a **14-day withdrawal right from taking possession**. At pickup inspect, and withdraw on the spot if anything is wrong. **At pickup sign only the handover protocol (Übergabeprotokoll), never a new order** — an order signed on the premises has no withdrawal right.
- **~10 % damages clause** for non-acceptance is standard; irrelevant if you withdraw lawfully.
- **Pre-ticked §476 side agreements** — typically: liability period cut to 1 year; exclusion of the software-update duty ("Ausschluss der Aktualisierungspflicht"). Valid once signed as separate declarations. Ask to strike; or accept knowingly, ideally against a written used-car guarantee valid in your country.
- **Place of signing:** strike the pre-printed dealer city/date and write your own city.
- **Non-refundable "Reservierungsgebühr"** in standard terms: ask to strike. A refundable reservation credited to the price is fine.
- Withdrawal notice: return transport is usually at the buyer's cost (amount stated in the notice); value loss is owed for use beyond testing — the drive home counts. Don't register the car in the destination before day 14 if in doubt.
- "No Russia/Belarus" export clause pages are standard in DE dealer packs; sign.
- Other countries have their own distance-sale rules — check before relying on remote signing.

## 4. Ready-to-send asks (DE + EN)

| Topic | DE | EN |
|---|---|---|
| Name | Bitte den Namen überall exakt wie im Ausweis/Aufenthaltstitel schreiben: „<Name>". | Please write my name exactly as on my ID: "<Name>". |
| Address | Bitte Anschrift korrigieren: <Straße>, <PLZ> <Ort>, <Land>. | Please correct the address incl. postcode and country. |
| 2-year liability | Bitte die Verkürzung der Verjährungsfrist auf 1 Jahr streichen; es soll die gesetzliche Frist von 2 Jahren gelten. | Please remove the 1-year cut; statutory 2 years. |
| Update duty | Bitte auch den Ausschluss der Aktualisierungspflicht streichen. | Please also remove the update-duty exclusion. |
| Condition | Bitte unter „Besondere Vereinbarungen": Lieferumfang und Zustand laut <Prüfbericht Nr., Datum>; Auto ist unfallfrei. | Under special agreements: scope and condition per <report no., date>; accident-free. |
| Items | 2 Fahrzeugschlüssel, COC-Papier, Zulassungsbescheinigung Teil I und II im Original, Ladekabel, digitaler Servicenachweis werden übergeben. | 2 keys, CoC, both registration parts (originals), charging cable, service proof handed over. |
| Wheels | Im Kaufpreis enthalten: zweiter Radsatz (<Größe>, <Reifen>). | Second wheel set (<size>) included in the price. |
| Guarantee | Bitte Garantiebedingungen, Laufzeit und Gültigkeit in <Land> schriftlich beifügen. | Guarantee terms, term and validity in <country> in writing, please. |
| Recalls | Bitte bestätigen, dass alle offenen Herstelleraktionen vor Übergabe erledigt werden. | Please confirm all open manufacturer campaigns are done before handover. |
| Confirmation | Bitte schriftliche Auftragsbestätigung nach Eingang. | Written order confirmation on receipt, please. |
| Invoice | Bitte auf der Rechnung die Anschrift mit „<Land>" ergänzen. | Please add the country to the address on the invoice. |
| CoC copy | Bitte vorab eine Kopie des CoC (alle Seiten). | A copy of all CoC pages in advance, please. |

Batch all asks into **one** email; the owner (or the outreach agent with the owner's OK) sends it.

## 5. Signing mechanics

- Owner signs in a PDF editor (Preview/iPad markup or a tablet signature the dealer offers), or print → sign → scan to **one** PDF. Return only the "to sign" file, by reply to the dealer's email.
- Before sending: every mandatory field signed, optional ones decided, place of signing changed, conditional §476 pages signed only if accepted.
- Keep the signed PDF in the scratchpad (or the owner's own private storage), never the repo.

## 6. Other countries

The method (§1) and red-flag table (§2) apply everywhere. Seller ≠ owner checks per country: [deposit-payment.md](deposit-payment.md) §6. Every country: the contract/invoice must **name the buyer** — it is the import filing at home.
