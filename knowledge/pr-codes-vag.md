# PR codes (VW / Audi / Škoda / Cupra / Seat) and options from photos

> Snapshot: researched Oct–Nov 2026. Prices, laws and tool behaviour drift — re-check anything you act on.

Confidence tags: **V** verified from a primary source (price list, OEM doc, dealer data), **A** anecdotal/forum/secondary, **I** inferred. Code tables were checked on 2023+ MEB EVs (ID.4/ID.5, Q4, Enyaq); the PR-code *system* is VAG-wide, but a given code's meaning can differ per model — confirm on the printout's plain text when it matters.

Related: [vin-sources.md](vin-sources.md) (free/paid VIN sources per country), [battery-soh.md](battery-soh.md).

## 1. What a PR code is, where to get the list

Every VAG car has a factory option list of 3-character **PR numbers**. Each **family** (the first 2 characters, e.g. `3F?`) holds exactly one code per car; the "basic" value of the family means the option is absent.

| Source | Where / how | Notes |
|---|---|---|
| **Vehicle data sticker** ("Fahrzeugdatenträger") | White label with VIN, model code, paint/interior codes and a block of 3-char codes. Classic VAG: spare-wheel well / boot floor + a copy in the service booklet. **MEB: stuck to the metal under the boot floor panel**, often the only copy (A, owner forum) | MEB has no paper service book (digital service plan, V owner's manual). Some dealers stick a copy on the "Dokumentation der Fahrzeugübergabe" page of the printed manual — not guaranteed |
| **Dealer printout** "Fahrzeugdaten" / "Fahrzeugidentifikation – Pr.-Nr. – Merkmal – Benennung" | Any VW/Audi/Škoda parts counter prints it from the VIN in ~1 min (ETKA / partslink24 / ElsaPro) | Full list with plain-text meanings. A courtesy, not a service: some refuse non-owners (GDPR). A dealer *selling* the car usually sends it at once. Swiss dealers often attach it to listings |
| **A/C refrigerant label** under the bonnet | **R744** = heat pump; **R1234yf** = no heat pump (V) | The one photo that settles the heat pump without the sticker |
| Brand apps (owner's account) | myVW shows refrigerant (heat-pump proxy, A); myAudi reportedly shows the full equipment list (A, unconfirmed) | Only useful if the seller checks for you |
| Infotainment | Shows the VIN under Service, **no** equipment list | — |
| Registration docs / CoC | **No** option list (DE ZB, PT DUA, FR carte grise, CoC). CoC only carries homologation data (tyre sizes) | — |

### Decoders (prices as of Nov 2026)

- **No free VIN decoder returns factory options for 2023+ MEB** — 10+ tried. Go straight to the sticker or dealer printout.
- **Free route:** sticker photo or dealer printout → type the codes into **oemwolf** (`https://oemwolf.com/wiki/pr/?search=3FU+9M3+4E6`, codes space-separated, works with curl) or `carhunt vin prcodes CODE…` (this repo's table, [`carhunt/vet/data/prcodes_vag.csv`](../carhunt/vet/data/prcodes_vag.csv)). oemwolf meanings are generic VAG; compare with the model tables below.

| Decoder | Free? | Options for 2023+ VAG? | Result |
|---|---|---|---|
| oemwolf.com | yes, no account | decodes typed codes only, no VIN lookup | Works |
| elcats.ru (ETKA-based VIN search) | yes | **no** | "no information" for every WVG/WAU/TMB test VIN — data too old |
| superETKA ("free VIN base") | **no** — $10/month or $50/year, 4 VINs/day | only paid | Cheapest full route when several cars need it; includes digital service history |
| vagvin.com | ~€6/VIN | yes (paid) | Cheapest per-VIN paid route |
| MecaVIN | €9–29/report | claims full option list + price | Not tested |
| CarWhere (Audi) | $9.99 after free check | US-focused | Not tested (JS-only form) |
| carVertical | free pre-check only | only in paid report (€27.99, €17.99 each in a 3-pack) | Pre-check just confirms the model |
| autoDNA, vindecoder.pl/.eu | free preview | no | Stuck behind Cloudflare Turnstile; pattern decode only |
| vindecoderz, fastcarcheck.uk, pr-codes.de, lenkradcode, vin.dekoder.pl, vin-decode.de, vinanalytics.eu, vag-vin.com, 7zap, partsouq, exist.ru, catcar, mdecoder, EpicVIN | — | no | 403 / DNS fail / no VIN feature / no options |

Rules:
- **No paid option decode (~€6/VIN) without the owner's OK for that specific car.** Most options show in photos.
- **Never create a decoder/site account with the user's email and keep the password in a file.** Credentials go through the creds helper only.
- Other brands have their own datacards: **Mercedes** — a free datacard by VIN exposes basic-spec ex-company cars sold as "Progressive". See [vin-sources.md](vin-sources.md).

## 2. Price-list codes ≠ sticker codes

- Price lists and dealer ads use **sales package codes**: VW `P??`/`W??` (PA2, PAK, PJ3, WD5…), Škoda `PHC`, `PLx`, `WH?`, Audi `PY?`/`PW?`/`PQ?`. The sticker lists the **underlying PR numbers**, sometimes with the package codes too. WHY: matching a price-list code against a sticker gives false "missing option" reads.
- Example (V): Audi `PYY` Komfortpaket plus appears on the sticker as `3L5` + `7P1` + `6XL`.
- Decode **by family**, not by exact string. A code outside the family's basic value = fitted.

## 3. Decode by family

Full table (201 rows, 137 codes, with confidence): [`carhunt/vet/data/prcodes_vag.csv`](../carhunt/vet/data/prcodes_vag.csv) — `code,family,option_key,meaning,confidence`; a code can have several rows (one per cardb option it implies); `meaning` starting `none:` = the option is absent. `option_key` uses cardb's canonical keys.

| Option (`option_key`) | Family | Fitted | Absent (basic) | Notes |
|---|---|---|---|---|
| Panoramic roof (`pano`) | **3F?** | 3FU Audi (V), 3FG VW fixed glass + blind (V); Škoda 3FU or 3FG (I) | **3FA** = no roof opening | Enyaq Coupé: fixed glass roof always, no blind |
| Electric tailgate (`power_tailgate`) | **4E?** | 4E7 electric (V), 4E6 + sensor/kick release, Škoda "virtual pedal" (V); VW LU standalone 5I6 | 4E0 / 4E2 / 4E5 = manual (A) | Audi Q4 45 MY24+: 4E7 standard |
| Electric seats (`electric_seats`) | **3L?** | 3L5 electric, no memory alone (V); 3L4/3L6/3L7/3L8 electric + memory (I); Audi NL 3PB driver only (V) | 3L0–3L3 = manual (A) | Electric **lumbar only** (7P1) is not e-seats |
| Seat memory (`memory_seats`) | 3L? / AI? / PV? | Audi AI1 (with 3L5, V), PV3 MY27 (V), PV6 other Audis (A); VW 1R3 ergoActive memory (A) | 3L5 without AI1 = no memory | VW EU MY24+: an e-seat always has memory + massage |
| Lumbar | 7P? | 7P1 4-way electric (V), 7P2 (I) | 7P0 / 7P4 | — |
| Massage / ventilation (`massage_seats`, `ventilated_seats`) | 4D? (VW massage also 8I6, A) | 4D? (I) | 4D0 | — |
| Premium audio (`premium_audio`) | **9V?** | 9VS = Audi SONOS (V; VW HK / Škoda Canton unverified); 9VG = VW Harman Kardon (A) | 9VD = basic Audi sound | VW HK also via RD3/RD9 Infotainment Plus (with AR-HUD) |
| Heat pump (`heat_pump`) | **9M?** + **KK?** | **9M3** (V), Audi MY27 9M8; cross-check **KK2 = R744** (V) | 9M0 or family missing; **KK3 = R1234yf** | Price-list: VW WPU/WPX, Škoda PHC |
| AC charger | KB? | KB2 7.2 kW (Q4 35 only), KB3 11 kW (I) | — | 11 kW is standard on the MEB 77/82 kWh cars — doesn't separate them |
| Matrix (`matrix_led`) | 8I? | VW 8IV; Audi PXC package; VW Design pack PA2/PA6 | VW 8IR plain LED | — |
| HUD (`hud`) | KS? | KS3 AR-HUD; VW RD3/RD9/RB2; Audi PYH (MY24–26) | — | — |
| Wheels | model-specific | Audi 40S/40Z 19", 55J/55K/56J/56H 20", 55L/C5W/C7A/C1P 21"; VW PJ? (Hamar/Drammen/Narvik/Bergen) | — | Easier: read size off the tyre sidewall |

## 4. The ask (sticker photo or printout)

Vet agents never message sellers: queue the ask with `carhunt evidence CAR` (writes an `ask` event the outreach agent sends). One ask per message; skip it if the ad photos already show the sticker. Keep these verbatim.

**Seller — sticker photo** (7 languages):
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

## 5. Options from photos (any visible option)

Works for any option with a visible cue (seats, tailgate, roof, audio, towbar, HUD, 360° camera…), any brand. Pattern: one agent per batch of cars views **every** photo and writes a strict verdict per option with photo evidence.

**Verdicts — be strict:**
- **yes** = the cue is *clearly* visible (e.g. switch panel or ergoActive strip on the driver seat's outer side; numbered 1/2/3 + SET memory buttons).
- **no** = the *absence* cue is clearly visible (height-pump lever, fore-aft bar, recline wheel on the driver seat).
- **unknown** = anything else. Write nothing for the option; record why: `cardb fact CAR <key>_photo_check="unknown: no driver-seat-side photo among 14":photo`.
- WHY: a wrong "no" hides a good car; "unknown" just triggers an ask.

**Rules:**
- **Source precedence.** Never overwrite an option whose source is `seller_said`, `vin_pr_code`, `inspection` or `owner`. On a conflict, write a fact instead: `cardb fact CAR <key>_conflict="photo <id>: <what is visible>":photo`. WHY: protected sources come from the car itself or the seller in writing.
- **Photo vs ad text:** a clearly visible direct cue beats a dealer's "full" equipment list — in validation the photo was right in every photo-vs-text conflict (seat memory strip, memory row and pano missing from "full" lists; a tailgate close button not listed). Set the photo value over `ad_text`/`ad_spec` and still log `<key>_conflict` so the trail stays.
- **Driver seat only.** A manual **passenger** seat says nothing about the driver seat (driver-only electric/memory packs exist, e.g. VW, Škoda Plus). Confirm which seat you are looking at (LHD: left front; check door/B-pillar orientation). "Manual" close-ups are often the passenger seat.
- **Backfill galleries before judging.** Many ads sit in the DB with only the cover photo while the live ad has a full gallery: fetch the gallery from the live listing into cardb first (site pacing rules apply; stop a site at its first block). WHY: many "unknown" verdicts come only from the DB holding just the cover photo.
- **Ask for the driver-seat-side photo.** Even with full galleries the seat base is usually cropped (dealer banners, interior shots framed above the cushion), so most stay unknown. Queue an ask for "a photo of the outer side of the driver's seat" (and the driver door card for memory buttons) via `carhunt evidence CAR`.
- **Exterior proxies are weak or useless** (painted arches, S line badge, light bar, black wheels); see §6. **Test any heuristic blind before using it** (§7).
- Evidence: every verdict records the photo id + what is visible (e.g. "photo 123: SET/1/2 buttons on driver seat side") in a fact or event next to the `cardb opt … :photo` write. Log one line per car: `car | yes/no/unknown | photo id | what's visible`.

Coverage to expect (MEB ads with full galleries): seat side visible in **57 %**, headliner **30 %**, speaker logo **24 %**, tailgate close button **18 %**.

## 6. Visual cue table

### Generic direct cues (any brand) — blind-validated on 67 VAG MEB ads

| Cue in photo | → option (`option_key`) | Hit rate vs ad text | Notes |
|---|---|---|---|
| Seat-side switch panel / ergoActive strip → yes; height lever / pump → no | `electric_seats` | 27/28 (+1 where photo was right) | Electric lumbar alone gives a small 4-way button, not the full switch set |
| Memory buttons (VW/Škoda seat side; Audi driver door card) | `memory_seats` | 23/25 (+2 photo-correct) | Rarely shown on Audi — ask for a door-card shot |
| Close button on the tailgate's inner trim | `power_tailgate` | 10/11 (+1 photo-correct) | Seen in only 18 % of ads. A tailgate switch on the driver door also exists on manual-tailgate cars — doesn't count |
| Glass roof seen from inside / solid headliner seen | `pano` | 15/16 (+1 photo-correct) | From outside often hidden by a black contrast roof |
| harman/kardon · SONOS · CANTON grille logo; plain grille → no | `premium_audio` | 13/13 | Needs a close-up |
| A/C label R744 / R1234yf | `heat_pump` | (V, label) | Heat pump is never otherwise visible |

### Example: VAG MEB rules, MY24–26 (model-specific, not current fact)

| Rule | Hit rate | Verdict |
|---|---|---|
| Audi Q4 45 → e-tailgate standard | 20/20 | use (price lists) |
| Audi framed tilt-tab interior mirror → no e-seats (MY24–26) | (V price list) | use |
| Audi black textured arches → no e-seats | 9/9 | use, weak (base exterior can still have PYY) |
| Audi painted/grey arches → e-seats | **0/14** | useless |
| Audi S line → e-seats | **1/14** | useless |
| VW Top-Sport seat with gloss-black cut-out headrest → e-seats (Top-Sport Plus) | refined cue | use the refined cue only; standard seats also look one-piece |
| VW separate-headrest seat → no e-seats | 22/26 | weak (Interior Style Plus keeps separate headrests) |
| VW plain cloth → no e-seats | 3/3 | small n |
| VW light bar → e-tailgate | 17/21 (base rate 22/31) | weak lift |
| VW no light bar → no e-tailgate | 3/8 | useless |
| VW black Bergen wheels → pano | **6/16** | useless |
| VW 360° camera (MY24–26) → e-tailgate (IQ.DRIVE) | (V price list) | use; not DE MY27 |
| Trim names, e.g. FR Life Max → e-tailgate 14/16; BE Pro Business → e-tailgate 4/4; FR Life Max 2024 → no e-seats 8/8 | — | per market; see brand research |
| Škoda Sportline / lit grille → driver e-seat memory + e-tailgate | 5/5 · 3/3 | use (nested packages) |
| Škoda plain Loft → no e-seats | 3/4 | weak |
| Enyaq Coupé → pano (fixed glass, no blind) | 3/3 | use |

Lessons: on VW and Audi the wanted options were **standalone packages on every trim** (only ~9/58 cars had e-seats), so trim/exterior cues mostly fail; Škoda's nested packages (Clever ⊂ Plus ⊂ Advanced ⊂ Maxx) are the exception. Small samples (Škoda n=15, Audi n=28).

## 7. Testing a heuristic blind

1. Pick cars with full galleries; split the work: **cue agents** log what is visible per photo set into a fixed schema (`seat_side_controls`, `memory_buttons`, `tailgate_close_button`, `pano`, `door_speaker_logo`, `arches`, `badges`, `front_light_bar`, `sticker_or_doc`… each `yes|no|unknown` + evidence photo) **without seeing ad text**.
2. **Truth agents** extract options from ad text only: `yes` on explicit mention (multi-language), `no` only when a full structured list lacks it, else `unknown`. `vin_pr_code`/`seller_said` options count as truth.
3. Truth = direct photo cue when visible, else text. Score each rule (hits/applicable) and re-check every photo-vs-text conflict by eye.
4. Keep only rules that beat the base rate clearly; mark "direct" cues as the trusted tier.

## 8. Per-ad scoring recipe (< 1 min/ad)

1. **Text pass:** explicit mention = yes; absence from a list = weak no only.
2. **Photo pass (direct cues):** e-seats ±4, memory +1, e-tailgate +3, pano ±1.5, audio logo +1 / plain −1 (example weights for one wish list — reweight for yours).
3. **Model rules** only when photos are silent (e.g. tables in §6).
4. Heat pump +1 only on text, R744 label or PR code.
5. Wheels 20"/21": −0.5 (comfort preference).
6. Precedence per option: photo → `vin_pr_code`/`seller_said` → other explicit yes → model rule → weak text no.
7. **Score ≥ 8: contact. 4–8 with key options unknown: ask for the driver-seat-side photo + PR sticker (§4). < 4: skip** unless the price is exceptional.
