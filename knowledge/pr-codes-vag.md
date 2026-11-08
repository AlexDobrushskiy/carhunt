# PR codes (VW / Audi / Škoda / Cupra / Seat) and options from photos

Related: [buy/doc-verify.md](buy/doc-verify.md). A code's meaning can differ per model: confirm on the printout's plain text when it matters.

## 1. What a PR code is, where to get the list

Every VAG car has a factory option list of 3-character **PR numbers**. Each **family** (the first 2 characters, e.g. `3F?`) holds exactly one code per car; the family's "basic" value means the option is absent.

| Source | Where / how |
|---|---|
| **Vehicle data sticker** ("Fahrzeugdatenträger") | White label with VIN, model code, paint/interior codes and a block of 3-char codes. Classic VAG: spare-wheel well / boot floor + a copy in the service booklet. MEB: under the boot floor panel, often the only copy |
| **Dealer printout** "Fahrzeugdaten" | Any VW/Audi/Škoda parts counter prints it from the VIN (full list with plain text). A dealer selling the car usually sends it on request |
| **A/C refrigerant label** under the bonnet | **R744** = heat pump; **R1234yf** = no heat pump |
| Registration docs / CoC | **No** option list |

Decode: type the codes into `carhunt vin prcodes CODE…` (bundled table [`carhunt/vet/data/prcodes_vag.csv`](../carhunt/vet/data/prcodes_vag.csv): `code,family,option_key,meaning,confidence`; a `meaning` starting `none:` = option absent) or oemwolf (`https://oemwolf.com/wiki/pr/?search=3FU+9M3+4E6`).

Rules:
- **No paid option decode without the owner's OK for that specific car.** Most options show in photos.
- Never create a decoder/site account with the owner's email; credentials go through `carhunt secret` / the creds helper only.

## 2. Price-list codes ≠ sticker codes

- Price lists and dealer ads use **sales package codes** (VW `P??`/`W??`, Škoda `PH?`/`PL?`/`WH?`, Audi `PY?`/`PW?`/`PQ?`). The sticker lists the **underlying PR numbers**. Matching one against the other gives false "missing option" reads.
- Decode **by family**, not by exact string: a code outside the family's basic value = fitted.

## 3. The ask (sticker photo or printout)

Vet agents never message sellers: queue the ask with `carhunt evidence CAR` (writes an `ask` event the outreach agent sends). One ask per message; skip it if the ad photos already show the sticker. Keep these verbatim.

**Seller — sticker photo:**
- **EN:** "Could you please send a photo of the vehicle data sticker with the PR codes? It's a white label with the VIN and many 3-character codes, usually under the boot floor panel, sometimes in the owner's/service booklet. If you're a dealer, the factory equipment printout by VIN works too."
- **DE:** "Könnten Sie mir bitte ein Foto des Fahrzeugdatenträgers mit den PR-Nummern schicken? Weißer Aufkleber mit FIN und vielen dreistelligen Codes, meist unter dem Kofferraumboden, manchmal in der Betriebsanleitung/im Serviceheft. Als Händler gerne auch den Fahrzeugdaten-Ausdruck (Ausstattung zur FIN)."
- **FR:** "Pourriez-vous m'envoyer une photo de l'étiquette des données du véhicule avec les codes PR ? Autocollant blanc avec le VIN et des codes à 3 caractères, en général sous le plancher du coffre, parfois dans la notice/le carnet. Pour un professionnel, la fiche d'équipement d'origine par VIN convient aussi."
- **ES:** "¿Podría enviarme una foto de la etiqueta de datos del vehículo con los códigos PR? Es una pegatina blanca con el bastidor y muchos códigos de 3 caracteres, normalmente bajo el piso del maletero, a veces en el manual/libro de mantenimiento. Si es concesionario, también sirve el listado de equipamiento de fábrica por bastidor."
- **NL:** "Kunt u een foto sturen van de voertuiggegevenssticker met de PR-codes? Een witte sticker met het VIN en veel codes van 3 tekens, meestal onder de laadvloer van de kofferbak, soms in het instructie-/onderhoudsboekje. Als dealer mag ook de uitdraai van de fabrieksuitrusting op VIN."
- **IT:** "Potrebbe inviarmi una foto dell'etichetta dati del veicolo con i codici PR? È un adesivo bianco con il telaio e molti codici di 3 caratteri, di solito sotto il piano del bagagliaio, a volte nel libretto d'uso/manutenzione. Se è un concessionario, va bene anche la stampa della dotazione di fabbrica da telaio."
- **PT:** "Pode enviar-me uma fotografia da etiqueta de dados do veículo com os códigos PR? É um autocolante branco com o VIN e muitos códigos de 3 caracteres, normalmente debaixo do piso da bagageira, às vezes no manual/livro de manutenção. Se for stand, também serve a listagem do equipamento de fábrica pelo VIN."
- **Optional second photo:** the A/C refrigerant label under the bonnet (R744 = heat pump).

**Any brand dealer — printout by VIN** (when the seller can't; replace `[VIN]`):
- **DE:** "Guten Tag, könnten Sie mir zur FIN [VIN] bitte die Fahrzeugdaten mit Ausstattungsliste (PR-Nummern) als PDF/Ausdruck per E-Mail schicken? Ich interessiere mich für das Fahrzeug. Vielen Dank!"
- **PT:** "Bom dia, poderiam enviar-me por e-mail a lista de equipamento de fábrica (códigos PR / dados do veículo) do VIN [VIN]? Estou a pensar comprar a viatura. Obrigado!"
- **ES:** "Buenos días, ¿podrían enviarme por e-mail el listado de equipamiento de fábrica (códigos PR / datos del vehículo) del bastidor [VIN]? Estoy interesado en el coche. ¡Gracias!"
- **FR:** "Bonjour, pourriez-vous m'envoyer par e-mail la liste d'équipement d'origine (codes PR / données véhicule) du VIN [VIN] ? Je suis intéressé par le véhicule. Merci !"
- **NL:** "Goedendag, kunt u mij de fabrieksuitrusting (PR-codes / voertuiggegevens) van VIN [VIN] per e-mail sturen? Ik heb interesse in de auto. Dank u!"
- **IT:** "Buongiorno, potreste inviarmi via e-mail l'elenco della dotazione di fabbrica (codici PR / dati veicolo) del telaio [VIN]? Sono interessato all'auto. Grazie!"

Decoded codes go to cardb with source `vin_pr_code`: `cardb opt CAR power_tailgate=yes:vin_pr_code`.

## 4. Options from photos (any brand)

Works for any option with a visible cue (seats, tailgate, roof, audio, towbar, HUD, 360° camera…). One agent per batch of cars views **every** photo and writes a strict verdict per option with photo evidence.

**Verdicts:**
- **yes** = the cue is *clearly* visible (e.g. switch panel on the driver seat's outer side; numbered 1/2/3 + SET memory buttons).
- **no** = the *absence* cue is clearly visible (height-pump lever, fore-aft bar, recline wheel on the driver seat).
- **unknown** = anything else. Write nothing for the option; record why: `cardb fact CAR <key>_photo_check="unknown: no driver-seat-side photo among 14":photo`. A wrong "no" hides a good car; "unknown" just triggers an ask.

**Rules:**
- **Source precedence.** Never overwrite an option whose source is `seller_said`, `vin_pr_code`, `inspection` or `owner`. On a conflict write a fact instead: `cardb fact CAR <key>_conflict="photo <id>: <what is visible>":photo`.
- **Photo vs ad text:** a clearly visible direct cue beats a dealer's equipment list. Set the photo value over `ad_text`/`ad_spec` and still log `<key>_conflict`.
- **Driver seat only.** A manual passenger seat says nothing about the driver seat (driver-only packs exist). Confirm which seat you are looking at (LHD: left front).
- **Backfill galleries before judging.** Fetch the full gallery from the live listing into cardb first when the DB holds only the cover photo (site pacing rules apply; stop a site at its first block).
- **Ask for the driver-seat-side photo** (and the driver door card for memory buttons) via `carhunt evidence CAR` when the seat base is cropped out.
- **Exterior proxies** (painted arches, trim badges, light bars, wheels) are weak; test any such rule blind (§6) before using it.
- Evidence: every verdict records the photo id + what is visible (e.g. "photo 123: SET/1/2 buttons on driver seat side") in a fact or event next to the `cardb opt … :photo` write. One line per car: `car | yes/no/unknown | photo id | what's visible`.

## 5. Direct visual cues

| Cue in photo | → option (`option_key`) | Notes |
|---|---|---|
| Seat-side switch panel / ergoActive strip → yes; height lever / pump → no | `electric_seats` | Electric lumbar alone gives a small 4-way button, not the full switch set |
| Memory buttons (seat side or driver door card) | `memory_seats` | Ask for a door-card shot when not shown |
| Close button on the tailgate's inner trim | `power_tailgate` | A tailgate switch on the driver door also exists on manual-tailgate cars — doesn't count |
| Glass roof seen from inside / solid headliner seen | `pano` | From outside often hidden by a black contrast roof |
| harman/kardon · SONOS · CANTON grille logo; plain grille → no | `premium_audio` | Needs a close-up |
| A/C label R744 / R1234yf | `heat_pump` | Not otherwise visible |

## 6. Testing a heuristic blind

1. Pick cars with full galleries. **Cue agents** log what is visible per photo set into a fixed schema (`seat_side_controls`, `memory_buttons`, `tailgate_close_button`, `pano`, `door_speaker_logo`, `arches`, `badges`, `front_light_bar`, `sticker_or_doc`… each `yes|no|unknown` + evidence photo) **without seeing ad text**.
2. **Truth agents** extract options from ad text only: `yes` on explicit mention, `no` only when a full structured list lacks it, else `unknown`. `vin_pr_code`/`seller_said` options count as truth.
3. Truth = direct photo cue when visible, else text. Score each rule (hits/applicable) and re-check every photo-vs-text conflict by eye.
4. Keep only rules that beat the base rate clearly; direct cues are the trusted tier.

## 7. Per-ad scoring recipe

1. **Text pass:** explicit mention = yes; absence from a list = weak no only.
2. **Photo pass (direct cues):** weight each wanted option for your wish list (e.g. e-seats ±4, memory +1, e-tailgate +3, pano ±1.5, audio logo +1 / plain −1).
3. **Model rules** (validated per §6) only when photos are silent.
4. Heat pump only on text, R744 label or PR code.
5. Precedence per option: photo → `vin_pr_code`/`seller_said` → other explicit yes → model rule → weak text no.
6. Set thresholds for contact / ask (driver-seat-side photo + PR sticker, §3) / skip on your scale.
