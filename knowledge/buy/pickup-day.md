# Pickup day

> Snapshot: researched Oct–Nov 2026. Prices, laws and tool behaviour drift — re-check anything you act on.

Tags: **V** verified from a primary/official source · **A** anecdotal/forum/secondary · **I** inferred.
Siblings: [contract-checklist.md](contract-checklist.md) · [deposit-payment.md](deposit-payment.md) · [doc-verify.md](doc-verify.md) · [shutdown.md](shutdown.md) · [../import/README.md](../import/README.md) · [../battery-soh.md](../battery-soh.md)

Assumes a signed remote order (DE dealer: withdrawal right runs from pickup — [contract-checklist.md](contract-checklist.md) §3).

## 1. Before travel (remote, ~1 week ahead)

- [ ] Written order confirmation received; final invoice draft names the buyer **with country**.
- [ ] Ask the dealer (one email): run **pending OTA updates and open campaigns/recalls** before handover; confirm original CoC, both registration parts, keys, cables, wheel set ready. WHY: a pending OTA is "one press" for the dealer; campaigns are easier before export.
- [ ] CoC copy in advance (all pages): every tyre size you'll use must be in it (§5).
- [ ] Transit plates + insurance booked to cover **drive + destination inspection visit (~30 days)**. DE: 30-day export plate (Ausfuhrkennzeichen), **not** the 5-day yellow short-term plate (FR/BE/NL/LU refuse it, **A**). Insurance card comes by post → order ~1 week ahead; registration offices need an appointment, closed Saturdays and Friday afternoons; HU (MOT) must cover the plate period; dealers often run it via their registration service (~€100–300 incl. insurance, ~2 h after 08:00) (**A**). Details: [../import/de-to-pt.md](../import/de-to-pt.md).
- [ ] Destination insurer: request your **claims-history declaration** from your current/previous insurer — a PT insurer asks for it to price the new policy (**A**).
- [ ] **Instant-transfer limit** checked/raised; VoP name noted ([deposit-payment.md](deposit-payment.md) §4).
- [ ] Book a **lift check** near the dealer if the dealer won't put it on theirs (independent garage or the manufacturer's service bay).
- [ ] Arrival: fly in the day before, or plan a late-morning start (plates take the morning).
- [ ] Route: winter rules on the way (DE §2(3a) StVO situational winter tyres; FR Loi Montagne 1 Nov–31 Mar in mountain areas: winter tyres or carried snow socks, **V**). Charging plan for the drive.
- [ ] Printouts/PDFs on phone: order, withdrawal notice + model form, inspection report, battery certificate, VIN.

## 2. At the car

- [ ] **Lift check: underbody and HV battery housing** (dents, scrapes, corrosion, leaks). WHY: lease-return inspections are often done without a lift ("eingeschränkt") so the underbody goes unchecked.
- [ ] VIN on the car (windscreen plate + type plate) = order = papers.
- [ ] Every defect the inspection report listed: fixed as the contract says? **Polishing can't remove chips** — chipped panels need touch-up/paint ([doc-verify.md](doc-verify.md)).
- [ ] Tyres: sizes vs CoC, tread depth, DOT age, snowflake mark; second wheel set (if included) present and as described.
- [ ] Keys (count), charging cable(s), tow-hitch parts, parcel shelf, first-aid/warning triangle.
- [ ] OBD/app SoH reading if useful — **read-only**, never clear codes; unplug the dongle after ([../battery-soh.md](../battery-soh.md)).
- [ ] 12 V battery ~14–15 V in "ready".
- [ ] OTA/software: confirm the pending update ran; open campaigns done (dealer printout of campaigns for the VIN).
- [ ] Short test drive: charging port opens, AC charge starts, no warnings.
- [ ] **Brand app:** buyer becomes **primary user**; dealer/previous owner **removed** from the car's account (otherwise they keep remote access/location) (**A**).
- [ ] Anything wrong → it's still a distance sale: withdraw on the spot (DE), or have it written into the handover protocol.

## 3. Paperwork (same sitting as payment)

Originals — no copies:

| Item | Note |
|---|---|
| Registration part I (DE: ZB I) | Original |
| Registration part II / title (DE: ZB II) | Original; its absence = lien risk ([deposit-payment.md](deposit-payment.md) §6) |
| **CoC** | Original. PT IMT fee €45 with CoC vs €165 without (**V**); a duplicate costs time (BE: ~€160) |
| Keys | All agreed (usually 2) |
| Charging cable(s) | As in contract |
| Second wheel set | If included |
| Service proof | Digital printout / service book; campaign printout |
| Inspection report, battery certificate | Original PDF (verifiable by QR / cert no.) |
| Final VAT invoice | Buyer name exactly as on ID, address **with country**; VAT shown |
| Export plates + insurance card | Covers ~30 days |
| **Handover protocol** | The **only** thing you sign at pickup — never a new order (DE: kills the withdrawal right) |

Payment: SEPA Instant with **VoP match** → papers + keys handed over in the same sitting ([deposit-payment.md](deposit-payment.md) §4).

## 4. After

- [ ] Photos of every original to the owner's private storage (not the repo).
- [ ] cardb: `cardb status CAR bought`, `cardb event CAR --type pickup --summary "picked up; lift OK; papers complete"`.
- [ ] Start [shutdown.md](shutdown.md) close-out for the backups.
- [ ] DE distance sale: don't register in the destination before day 14 if any doubt remains — the withdrawal right runs 14 days from pickup and value loss grows with use (**I**).
- [ ] Destination registration: [../import/README.md](../import/README.md) (PT reference: [../import/pt-registration.md](../import/pt-registration.md)). At the legalisation hand over the original CoC and check the new registration lists **all** CoC tyre sizes before leaving the counter.

## 5. Tyre/CoC rules (generic)

- **Any size in the CoC is legal**, even if the registration document lists only one (DE: ZB I fields 15.1/15.2 show one size; CoC field 32 or 50 lists the rest) (**V**, ADAC).
- PT registration (DUA) has front/rear tyre fields; extra sizes go under "Anotações especiais"; imported cars usually get CoC sizes copied (**A**, forums). Adding a size later (*averbamento*): ~€30 IMT + ~€100 declaration (**A**).
- PT periodic inspection fails a size only if **not on the registration AND outer diameter >5 % different** (**V**, inspection manual 2006 version).
- **Mixing winter and summer tyres across axles: legal in PT** (inspection fails only mixed types on one axle, **V**). PT has no winter-tyre requirement; non-studded winters legal all year (**A**).
- **DE in winter conditions** (snow, ice, slush, frost): **all wheels** need the snowflake (3PMSF) mark (§2(3a) StVO, **V**). A winter-front/summer-rear mix is illegal then — and unsafe on a RWD car (better grip belongs on the rear, **A**, ADAC). → **Drive home on a matched set**; carry the other set in the boot.
- Winter tyres in a hot climate brake markedly worse; ADAC advises against summer use of winter tyres deeper than 4–5 mm (**A**, ADAC test) — replace rather than run them out.
- Load/speed index must meet the CoC; indirect TPMS needs a reset after a wheel swap.
