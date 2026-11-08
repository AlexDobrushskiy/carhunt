# Pickup day

Siblings: [contract-checklist.md](contract-checklist.md) · [deposit-payment.md](deposit-payment.md) · [doc-verify.md](doc-verify.md) · [shutdown.md](shutdown.md) · [../import/README.md](../import/README.md)

Assumes a signed remote order (DE dealer: withdrawal right runs from pickup — [contract-checklist.md](contract-checklist.md) §3).

## 1. Before travel (remote, ~1 week ahead)

- [ ] Written order confirmation received; final invoice draft names the buyer **with country**.
- [ ] Ask the dealer (one email): run **pending OTA updates and open campaigns/recalls** before handover; confirm original CoC, both registration parts, keys, cables, wheel set ready.
- [ ] CoC copy in advance (all pages): every tyre size you'll use must be in it (§5).
- [ ] Transit plates + insurance booked to cover the drive **plus** every destination step that needs the car present (see your import guides, [../import/README.md](../import/README.md)). Check how the insurance card arrives (often by post) and the plate office's appointment rules and hours.
- [ ] Destination insurer: request your **claims-history declaration** from your current/previous insurer if the new insurer prices on it.
- [ ] **Instant-transfer limit** checked/raised; VoP name noted ([deposit-payment.md](deposit-payment.md) §4).
- [ ] Book a **lift check** near the dealer if the dealer won't put it on theirs (independent garage or the manufacturer's service bay).
- [ ] Arrival: fly in the day before, or plan a late-morning start (plates take the morning).
- [ ] Route: winter-tyre rules of every country on the way; charging plan for the drive.
- [ ] Printouts/PDFs on phone: order, withdrawal notice + model form, inspection report, battery certificate, VIN.

## 2. At the car

- [ ] **Lift check: underbody and HV battery housing** (dents, scrapes, corrosion, leaks).
- [ ] VIN on the car (windscreen plate + type plate) = order = papers.
- [ ] Every defect the inspection report listed: fixed as the contract says? **Polishing can't remove chips** — chipped panels need touch-up/paint ([doc-verify.md](doc-verify.md)).
- [ ] Tyres: sizes vs CoC, tread depth, DOT age, snowflake mark; second wheel set (if included) present and as described.
- [ ] Keys (count), charging cable(s), tow-hitch parts, parcel shelf, first-aid/warning triangle.
- [ ] OBD/app SoH reading if useful — **read-only**, never clear codes; unplug the dongle after.
- [ ] 12 V battery ~14–15 V in "ready".
- [ ] OTA/software: confirm the pending update ran; open campaigns done (dealer printout of campaigns for the VIN).
- [ ] Short test drive: charging port opens, AC charge starts, no warnings.
- [ ] **Brand app:** buyer becomes **primary user**; dealer/previous owner **removed** from the car's account (otherwise they keep remote access/location).
- [ ] Anything wrong → it's still a distance sale: withdraw on the spot (DE), or have it written into the handover protocol.

## 3. Paperwork (same sitting as payment)

Originals — no copies:

| Item | Note |
|---|---|
| Registration part I (DE: ZB I) | Original |
| Registration part II / title (DE: ZB II) | Original; its absence = lien risk ([deposit-payment.md](deposit-payment.md) §6) |
| **CoC** | Original; a duplicate costs time and money |
| Keys | All agreed (usually 2) |
| Charging cable(s) | As in contract |
| Second wheel set | If included |
| Service proof | Digital printout / service book; campaign printout |
| Inspection report, battery certificate | Original PDF (verifiable by QR / cert no.) |
| Final VAT invoice | Buyer name exactly as on ID, address **with country**; VAT shown |
| Export plates + insurance card | Cover the whole transit window |
| **Handover protocol** | The **only** thing you sign at pickup — never a new order (DE: kills the withdrawal right) |

Payment: SEPA Instant with **VoP match** → papers + keys handed over in the same sitting ([deposit-payment.md](deposit-payment.md) §4).

## 4. After

- [ ] Photos of every original to the owner's private storage (not the repo).
- [ ] cardb: `cardb status CAR bought`, `cardb event CAR --type pickup --summary "picked up; lift OK; papers complete"`.
- [ ] Start [shutdown.md](shutdown.md) close-out for the backups.
- [ ] DE distance sale: don't register in the destination before day 14 if any doubt remains — the withdrawal right runs 14 days from pickup.
- [ ] Destination registration: your import guides ([../import/README.md](../import/README.md)). At registration hand over the original CoC and check the new registration lists **all** CoC tyre sizes before leaving the counter.

## 5. Tyres and the CoC

- Every tyre size you will use must be in the CoC; check the new registration lists them all.
- Load/speed index must meet the CoC; indirect TPMS needs a reset after a wheel swap.
- Drive home on a matched set (all four the same type); carry the other set in the boot.
