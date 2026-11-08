# VIN & history sources (EU used cars)

> Snapshot: researched Oct–Nov 2026. Prices, laws and tool behaviour drift — re-check anything you act on.

Tags: **V** verified live on the official/provider source · **A** anecdotal/secondary (press, forum, snippet) · **I** inferred, not researched — verify before relying on it.

Related: [battery-soh.md](battery-soh.md) · [pr-codes-vag.md](pr-codes-vag.md) (options by PR code) · [coverage-rules.md](coverage-rules.md) (recall/warranty/goodwill logic) · [buy/contract-checklist.md](buy/contract-checklist.md) · [import/README.md](import/README.md).

Tools: `carhunt vin decode VIN` (WMI/plant/model year) · `carhunt vin check-digit VIN` · `carhunt vin rdw PLATE` (NL open data) · `carhunt vin prcodes CODE…` · `carhunt evidence CAR` (what's still missing; writes `ask` events — vet agents never message sellers). Record every result: `cardb fact CAR vin_check="<date>: <result>":<source>`.

---

## 0. Order of work

1. **Own free checks first** (decode, plate date, recall tools, auction archive, US screen, country register). ~10 min, €0. Only then ask the seller, **one item per message, in a fixed order, skipping what the ad/photos already show**. WHY: short asks get answers; multi-question openers get ignored.
2. **Paid reports only for finalists** (a car the buyer would actually travel to) — see §4.
3. Every claim you relay carries its source and tag; any number you computed (months owned, SoH %, km/yr) is relayed only after re-checking the date maths and stating assumptions. WHY: a wrong technical claim spreads fast across agent briefs.

## 1. Which countries' sources apply

Build the car's **history-country chain** before picking sources:

| Signal | Where to read it | Means |
|---|---|---|
| First registration anywhere | PT DUA field **B**; EU registration doc field **B**; NL RDW `datum_eerste_toelating` | country/date of the first owner |
| Current-country registration | field **I** (date of *this* registration); RDW `datum_eerste_tenaamstelling_in_nederland` | B ≠ I ⇒ imported |
| Seller country | ad | where documents/registers live now |
| Plate date later than claimed first reg | §7 | undeclared import — ask the origin |
| WMI / market | `carhunt vin decode` (§6) | China/US-market car = different product |
| Ad words | "importado", "Import", "Reimport", "EU-Neuwagen", "ex-…" | import, origin often omitted |
| Photos | cluster/MMI language, km vs miles, foreign service stamps, old plate in photos, inlet type | origin hints (**I**) |

Apply: **free sources of every country in the chain** (§3) + an **EU-wide paid report** for finalists with ≥1 foreign country (§4) + the **US salvage screen** when anything hints at America (§5b). A national car with a full brand service printout can skip the paid report.

## 2. Test every checker with a control first

**Many checkers print plausible text for any input.** Before you trust a "not affected / not found / eligible", run in the same session:

1. **Fake VIN**: the real VIN with the last 6 digits changed (e.g. `…999999`), or a nonsense one. Must give a *different* answer (error / unknown).
2. **VIN ±1**: last digit changed by one. For a hit ("recall open"), the neighbour should usually say "not affected".
3. **Known positive**: a VIN/plate you *know* has a record (a lot you opened on the archive's public lot pages, an earlier confirmed hit, a known-recalled sibling). It must still be found — proves search/login works.

Only a result that differs from the controls counts. Log the controls with the result.

| Case | Lesson |
|---|---|
| Audi DE "Feldmaßnahmen" VIN tool said "not affected" for a fake all-Z VIN too | answer was meaningless; Audi/VW/Cupra have no usable public recall check |
| EpicVIN preview showed the same "at least 4 records" for a made-up VIN of the same model | record counts are per-model marketing, not data |
| PT ACAP recall tool returns 0 for anything — it doesn't validate that a plate exists; and showed 0 for a car the brand checker listed 2 open campaigns on | ACAP "0" = no *inspection-blocking* recall only |
| Toyota PT recall checker said "covered by a recall" — proven real only because VIN ±1 said "not covered" and a dummy plate said "not detected" | controls turn a plausible message into evidence |
| Toyota PT warranty-extension simulator page always says "eligible" (it sends `makeFullValidations=false`) | call it with `true` and compare to a known-eligible control plate |
| carsbat "0 lots" accepted only after a known-positive VIN was found in the same logged-in session | a logged-out or broken search also returns 0 |
| Kia EU recall page: Submit sends no request at all | watch the network tab; silence ≠ "no recall" |
| vPIC labelled a Toyota BEV as "Highlander"; EpicVIN mislabelled an EU model year; RealOEM matched a 1976 car on serial collision | cross-check model/series against the documents |

## 3. Per-country sources

Access routes: **http** = curl/API · **lane** = logged-out automation browser · **plain-chrome/identity** = Cloudflare/Turnstile blocks automation · **account** = free login needed · **e-ID** = national digital ID needed · **seller** = only the owner can pull it and forward.

| Country | Free | Paid | Reveals | Access | Tag |
|---|---|---|---|---|---|
| **PT** | Plate-series calculator (seriedematriculas.pt) | — | PT registration date ±2 wk (community tracker, not IMT) | lane | V |
| PT | DUA/Certificado de Matrícula photo | — | B (1st reg anywhere) vs I (PT reg), E = VIN | seller | A (EU field scheme) |
| PT | ACAP recall (recall.motordata.pt), plate or VIN | — | open recalls **that fail the periodic inspection only** (open recall = IPO fail since 1 Mar 2026) | lane, no captcha | V |
| PT | — | **Certidão permanente** (IRN) **€10**, valid 6 mo | current owner (leasing/rental co./bank?), reserva de propriedade, penhora, leasing, pending registrations; probably *not* prior owners | anyone, plate only; seller's access code = free view | V |
| PT | — | IMT inspection certificate €27 | IPO results + km. **Empty under 4 yr** (1st IPO at 4 yr from field B) | IMT Online login | V |
| PT | ASF insurance check by plate (past dates) | — | was it insured in PT on date X (time-in-PT proxy) | reCAPTCHA → by hand | V |
| PT | — | carVertical **PT site** | foreign history | http; PT-plate lookup fails for fresh plates → use VIN | V |
| **ES** | DGT *informe reducido* | DGT *informe completo* €8.67 (2026 fee); resellers ~€10–20 | ITV history, km, owner count, cargas/embargos, **reserva de dominio**, pending recalls | anyone may request; online needs **e-ID** (Cl@ve/DNIe/cert) → reseller/gestoría | V/A |
| **FR** | **HistoVec** link + non-gage certificate | Autoviza, carVertical | owners, insurer-expert claims (VE/VGE), liens, stolen, CT km (none before 4 yr) | **seller** generates the link (valid 30 d); buyer can request from the site | A (JS-only site) |
| **DE** | no public register. Ask: ZB II front page (field (1) = previous keepers), latest HU report (km; first HU at 3 yr), brand digital service record printout | carVertical / CARFAX (strong DE data, claimed) | keepers count, km, service trail | **seller**/dealer | A |
| DE | brand VIN recall tools (§8); KBA DB has **no VIN field** | — | recalls | per brand | A |
| **NL** | **RDW open data** by plate (`carhunt vin rdw PLATE`) | — | import date (two date fields), odometer verdict *logisch/onlogisch*, open recall, APK due, export flag, insured. **No km values, no owner count** | http, no key | V |
| NL | Finnik free check | Finnik premium **€4.99** | owner-type timeline with dates (importer→lease→dealer→private), owner count, imported, past for-sale dates; premium: km history, options | lane (sum captcha) | V |
| NL | **RDW-Voertuigrapport** | — | all km readings, owner count, recalls, APK, status history (incl. BE readings since 2025, DE readings for cars imported after Feb 2026) | **seller** (DigiD), free, emailed PDF | V |
| **BE** | **Car-Pass** — mandatory for any sale to a private buyer, <2 months old (seller pays €11.10); verify number/QR on car-pass.be | — | km history, maintenance, open recalls, pending post-accident inspection, optional battery SoH (2026+) | **seller** gives number/QR → buyer verifies online | V |
| BE | public.car-pass.be/recalls by VIN | — | open recalls, BE cars only | lane | V |
| **LU** | not researched. Ask for the registration certificate + service record | EU-wide report | — | seller | I |
| **IT** | not researched. Likely: PRA *visura* by plate (owner, liens/fermo), Portale dell'Automobilista last-revisione km | EU-wide report | — | likely e-ID/reseller | I |
| **AT** | not researched. No public history register known; ask for Zulassungsschein + latest §57a ("Pickerl") report + service record | EU-wide report | — | seller | I |
| **Other** | not researched. Known free registers to try: PL historiapojazdu.gov.pl (plate+VIN+1st-reg date), CZ STK odometer lookup, DK motorregister, UK MOT history (RHD!) | EU-wide report | — | varies | I |

Seller-side proofs that settle more than any database: registration document (all parts), brand service printout, latest inspection report, purchase invoice (proves "bought new"), CoC.

## 4. EU-wide paid reports

**Rule: no report per candidate.** Buy only for finalists, **in bulk, on the cheapest market site**. WHY: ~€25 × dozens of cars; carVertical's PT site was ~40% cheaper than its DE site for the same report.

| Service | Price (EUR incl. VAT, 2026-10-31) | Validity | Notes | Tag |
|---|---|---|---|---|
| carVertical **PT site** | 1 €24.99 · 2 €33.98 · 3 €41.97 | 6 mo | DE site: 1 = €38.99. Always compare market sites | V |
| carVertical packs (open to individuals) | 10 €119.90 · 30 €299.70 · 100 €899 | 6 mo | best per-report if ≥6–7 finalists in 6 months | V |
| carVertical subscription | 10/mo €99.90 | reports expire 30 d, auto-renew | not worth it; no unlimited plan | V |
| carVertical free precheck | €0 | — | only "records found", no counts | V |
| CARFAX EU | 1 from €29.99 · 3 €49.99 · 5 €74.99 | **credit 4 years** | best for a slow trickle of VINs; 30-day money-back | V |
| autoDNA | 1 €24.99 · 3 €49.99 · business 20 €259 | 90 d / 210 d | free preview stuck behind Turnstile | V |
| Finnik (NL plates) | €4.99 | — | see NL | V |
| Vincario | 3 free decodes/mo | — | decoder/API, not history | V |
| EpicVIN | see §5b — **never pay** | | | V |

- ~20% carVertical coupons come and go (A).
- **None of these measures battery health** → [battery-soh.md](battery-soh.md).
- What they add: foreign km from service/inspection records, **past-ad snapshots with photos**, damage records. Coverage claims (DE strong) are the providers' own (A).

## 5. Auction archives & US salvage

### 5a. EU auction archive: carsbat.com (free account)
- Holds OpenLane/BCA-type lots: sale date, country, price history, km, damage flag, keys, seller type, ~30 photos (V).
- **Access:** Cloudflare → lane/curl fail; use **plain-chrome/identity**. VIN search needs login; lot pages are public. Photos need the browser session (curl 403).
- Create the account with the project's dedicated mailbox and the creds helper — see §10.
- **Positive-control rule:** before trusting "not found", search a VIN you know is archived (take one from any public lot page) in the **same logged-in session**. Also try partial VIN (last 8, first 13).
- A hit on a "1st owner, never damaged" car = big red flag; a hit with "Damage: No" still gives a dated km/price anchor.

### 5b. US salvage screen (1 minute, €0)
Run for any VIN that looks US-built/US-market or a seller saying "from America" (and cheaply for every import):
- **EpicVIN free preview** (no payment) — flags "SALVAGE ALERT", accidents, mileage for real US salvage cars (V, tested on a public Copart salvage EV).
- **stat.vin** — free Copart/IAAI lot pages with photos; Cloudflare → plain-chrome only (V).
- **Never pay EpicVIN.** The $1 "3 days" trial = up to 5 reports, then **auto-renews at $99.99/month**; cancel only inside the account; reports vanish when cancelled; refunds only for empty/double-charged reports. It has **no European data** (0 records / can't decode EU VW VINs) (V).
- US-market EVs have a CCS1 (J1772 + 2 DC pins) or NACS inlet, not CCS2 (I/A). A re-import's EU first-reg date is far later than its build date (I).

## 6. WMI / market flags

| Flag | Meaning | Action | Tag |
|---|---|---|---|
| **L…** WMI (e.g. LFV FAW-VW, LSV SAIC-VW, LBV BMW Brilliance domestic) on a brand you'd expect from Europe | **China-market car**: likely GB/T charging (two round inlets, ~100 kW DC cap), no EU warranty (dealer systems flag L-VINs), China telematics/maps, weak resale | treat as a different product; drop unless original EU paperwork | V/A |
| EU-market China-built exceptions | e.g. BMW iX3 G08 built in China carries a **WBY** EU WMI | don't flag on plant alone | V/A |
| Battery size ≠ EU spec (e.g. 84 vs 82 kWh gross) | China-spec pack | second independent tell | V (a "Q4 importado" turned out to be a Foshan-built China car) |
| **XPeng** | EU and China cars share a WMI | only remote test = **photo of the charging inlet** (CCS2 vs GB/T vs CCS1/NACS) | A |
| US WMI / CCS1 / NACS inlet / km in miles | US-market car | §5b salvage screen; check lighting/homologation | I |
| Check digit (pos 9) | mandatory in NA/China; many EU makers use it (VW, BMW, Toyota seen valid); EU Kia doesn't | invalid digit alone is not a red flag on an EU car | V/A |
| Pos 10 | model year on most VINs; **not** on EU BMW and EU Toyota | don't derive MY from it there | V |
| Build date | Toyota recall API and RealOEM (BMW) give production date/month; otherwise estimate from serial neighbours with known dates | needed for recall build windows | V / I |

`carhunt vin decode` covers WMI/plant/MY; NHTSA vPIC is good for maker + plant only (V).

## 7. Plate date vs first-registration date

A local plate issued later than the ad's first-registration date = **undeclared import** → ask "which country was it first registered in?" WHY: PT ads claiming "nacional" regularly contradict themselves this way.

| Country | Plate datable? | How | Tag |
|---|---|---|---|
| PT | yes, AA-00-AA since 03/2020, ~0.9 letter-pair series/month | seriedematriculas.pt calculator (±1–2 wk) | V |
| NL | not needed | RDW gives both dates directly | V |
| ES, IT, FR (SIV, 2009+), BE (2010+) | sequential national series | dating by series sightings | I |
| DE, AT | no (local district codes, reissued) | use documents | I |

## 8. Registration documents: fields to read

| Doc | Field | Use | Tag |
|---|---|---|---|
| EU harmonised (Dir. 1999/37/EC) | **B** first registration anywhere · **I** date of this registration · **E** VIN · **C.1** holder | B ≠ I ⇒ import; E must equal the VIN plate/windscreen | A |
| PT DUA | B vs I; holder vs seller | as above; owner name must match seller ID | A |
| DE ZB I / **ZB II** | ZB II field **(1) = number of previous keepers**; only current keeper named | >2 keepers on a 2–3-yr car = ask; **no original ZB II = bank lien likely** (buying without checking is gross negligence) | A |
| FR carte grise | **C.1** may name a lessor (LOA/LLD) | seller ≠ owner trap | A |
| ES permiso | DGT informe shows **reserva de dominio** | finance still owed | V/A |
| BE CIM | **not proof of ownership**; "Pro Business" trims often ex-lease | ask for the sale/lease buyout invoice | A |
| NL kenteken | part I/II + RDW dates | import, owner changes (`datum_tenaamstelling`) | V |

Seller's ID must match the registered keeper; seller ≠ owner is the top private-sale trap. Read every page yourself, not another agent's summary: VIN, km sequence, dates, issuer, edit marks.

## 9. Brand registry

| Brand | Recall checker by VIN | Warranty / extension check | Options / datacard by VIN | Battery-health route | Quirks |
|---|---|---|---|---|---|
| **Toyota / Lexus** | Toyota EU recall API: `GET https://kong-proxy-aws.toyota-europe.com/dxp/forms/recall/{pt/pt\|de/de}/{VIN}` with header `Origin: https://www.toyota.de` → production date, `recallsActive`, codes, stopDrive (V, curl, no captcha). **PT:** toyota.pt campanhas-técnicas checker (VIN or plate) | **PT:** Toyota Relax simulator (toyota.pt, plate) — call backend with `makeFullValidations=true`, needs the page's Bearer token (curl 401; in-page fetch works) (V). Relax follows the car regardless of owner; excludes only cars not sold by a European Toyota entity; traction cells not in Relax (V, T&C) | production date via the recall API | yearly **EV Health Check** printouts — also keep the battery cover chain (up to 10 yr / 1M km) alive; a missed year can break it (A/V-doc) | toyota.pt checker: reCAPTCHA once, then in-page `fetch` works; dealer codes on Health Check printouts aren't the public dealer IDs; dealer API (`kong-proxy-intranet…/dealers/api/toyota/<cc>/<lang>/…`) gives contacts by curl |
| **BMW / MINI** | vehiclerecall.bmwgroup.com (`brand=bmw\|mini`, market param) (V) | "BMW Battery Certificate" first 160k km, transfers (A) | **RealOEM** by last 7 chars: series, market, production month (V; check the series matches — serial collisions) | dealer "Battery Health Quick Report" (Premium Selection) (A); DIY EVScanner | hCaptcha + **~1 query per 20+ min** (429); lane blocked, plain-chrome passed; bimmer.work now paywalled; mdecoder daily limit |
| **Mercedes** | mercedes-benz.de recall form (FIN, no login) (V page, untested) | digital service booklet — any MB dealer prints it (A) | free datacard by VIN (e.g. lastvin.com, Turnstile) (A) — exposes basic-spec ex-company cars advertised as a higher line; mb.vin 429 | dealer XENTRY "Batterie-Zertifikat" (some DE ads include one); **not DIY-able** | rate limits on datacard sites |
| **VW / Audi / Skoda / Cupra** | **none usable** for VW/Audi/Cupra (Audi DE tool answers "not affected" for fake VINs); Skoda DE form "weitere Rückrufaktionen" (V page) | dealer printout of the digital service plan + **open campaigns** ("offene Aktionen", ElsaPro) | **no free decoder works for 2023+ MEB** (10+ tried) → photo of the **PR-code sticker** under the boot floor, decode at oemwolf / `carhunt vin prcodes` → [pr-codes-vag.md](pr-codes-vag.md); or dealer "Fahrzeugdaten" printout | dealer "Batteriezertifikat" (paid); DIY Car Scanner/CellPulse | **No paid option decode (~€6/VIN) without the buyer's OK for that car** (§10); NL RDW / BE Car-Pass show open recalls for local cars |
| **Kia / Hyundai** | Kia IT form (Italian list only — weak) (V); Kia EU page broken; Hyundai none (DE check showed nothing even when campaigns existed, A) | Kia 7 yr/150k transfers if serviced on schedule; import → check with a local dealer by VIN (A) | none free | dealer GDS printout; Hyundai DE partners with Aviloo (V); DIY Car Scanner (E-GMP 100% caveat) | MyKia/Bluelink app screenshots of service history |
| **XPeng** | none found | importer paperwork | none | Aviloo FLASH; XPeng service printout; DIY custom PIDs | inlet photo is the only market test (§6) |
| **All, PT** | ACAP (IPO-relevant only) | — | — | — | treat 0 as "nothing inspection-blocking" |
| **Other brands** | not researched (I) — look for "recall"/"Rückruf"/"campanhas" + VIN on the brand's national site, then run §2 controls | | | | |

VAG PR codes: **price-list package codes are not the sticker's PR codes** — decode by family (3F? pano roof, 4E? tailgate, 3L? seats, 9M3/KK2 heat pump; an R744 refrigerant label under the bonnet = heat pump). Detail: [pr-codes-vag.md](pr-codes-vag.md).

Dated examples of per-VIN battery recalls (2026-10/11, check build windows, don't treat as current): Mercedes EQA/EQB HV-battery recall (charge ≤80%/park outdoors until fixed; a car with the battery already replaced is the better buy); VW MEB battery-module recall (build window 2022–Aug 2024; a borderline build date needs a dealer campaign printout); Kia EV6 charging-unit (ICCU) campaign (builds to Feb 2024). How to weigh an open recall: [coverage-rules.md](coverage-rules.md).

**Asking the brand directly:** generic brand-support and dealer "geral@" inboxes tend to give no reply or an auto-ack within 24 h, and support often misreads the question. Prefer: brand web contact form (creates a ticket) → a phone call by the buyer → dealer after-sales address → generic inbox last. **Faster:** ask the seller for a screenshot of the brand app's warranty/service screen. Brand emails only with the buyer's approval, capped (2 + 1 follow-up).

## 10. Hard rules

- **No paid VIN option decode (~€6/VIN) without the buyer's explicit OK for that specific car.** Most options show in photos.
- **Never create a site account with the buyer's/owner's personal email, and never store a password in plaintext** (scratchpad, notes, logs). Accounts use the project's dedicated mailbox; credentials go only through `carhunt secret` / the creds helper and are never printed.
- No payments for trials (EpicVIN etc.). No seller contact from vet agents — write `ask` events via `carhunt evidence`.
- Close every browser you open; Cloudflare sites (carsbat, stat.vin, vindecoderz) need plain-chrome/identity; autoDNA/vindecoder previews stall behind Turnstile.
- Keep personal data from documents (IDs, contracts) in the scratchpad, never in the repo.
