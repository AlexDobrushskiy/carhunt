# Portugal: registering a used car bought in another EU country (destination side)

> Snapshot: researched Oct–Nov 2026 (EV run). Prices, laws and tool behaviour drift — re-check anything you act on.

Tags: **V** verified (official/primary) · **A** anecdotal/forum/commercial · **I** inferred. PT-specific throughout. Seller-country halves: [de-to-pt.md](de-to-pt.md), [fr-to-pt.md](fr-to-pt.md), [es-to-pt.md](es-to-pt.md), [be-to-pt.md](be-to-pt.md), [other-to-pt.md](other-to-pt.md). Module overview: [README.md](README.md).

## 1. The order (the one thing to get right)

**Homologation (online, free) → Category B inspection (car present) → DAV customs declaration (online, ≤20 working days from entry; PT plate number assigned on it) → plates + PT insurance → IMT counter/post (original foreign registration within 10 days of the DAV) → IRN ownership registration.** **V** (AT "Etapas" flow chart; gov.pt ISV page upd. 17.06.2026; gov.pt matrícula page upd. 04.09.2026; IMT "matrícula para veículos usados")

- **Commercial blogs put the DAV first, which is wrong.** The DAV needs the homologation declaration and the Modelo 112 inspection report as uploads. (EV run 2026-11-04: an import-agency blog had the order reversed.)
- **Consequence:** the car must still be legally drivable in PT until the inspection, so the **transit plate + insurance from the seller country must cover the drive plus the inspection visit — plan ≈30 days**. Book the Category B inspection slot **before** collecting the car. Per seller country: DE 30-day export plate, FR own temporary insurance ≥3 weeks on the French plate, ES seller deregisters after the inspection, BE X plate (30 days, no extension), NL/IT effectively truck/trailer.
- An expired transit plate gives **no legal basis to drive**: truck or trailer the car to the inspection centre (or have the transporter deliver there). **V** (Código da Estrada art. 117(1)) / **A** (forum report, Aug 2025: a trucked car taken plateless to the inspection).

## 2. Steps in detail

| # | Step | Where / how | Fee (2026) | Time | Deadline |
|---|---|---|---|---|---|
| 0 | Credenciação in the Sistema de Fiscalidade Automóvel (SFA2) — AT FAQ 11 says companies/representatives only; other gov.pt text says credential first. Do it once, early | Portal das Finanças → Alfândegas → Credenciação | 0 | — | before arrival |
| A | **Homologation declaration** (EU type approval → PT national number). Upload the foreign registration (field K must show `e1*…`-style EU approval) + CoC | Online, IMT portal ([chnac](https://www.imt-ip.pt/veiculos/introducao-a-homologacao/consulta-de-registos-de-homologacao/)); can be done **before the car arrives** | **free** ("isento de taxa") **V** | ~2–5 days **A** | before B |
| B | **Inspeção para atribuição de matrícula** at a **Category B** CITV → **Modelo 112** (valid 90 working days). CoC suffices; no individual homologation for an EU-type-approved car | In person, **car present**. Only some CITVs are Category B — book ahead ([IMT CITV list](https://www.imt-ip.pt/veiculos/inspecao-de-veiculos/centros-de-inspecao-tecnica-de-veiculos-citv/)) | **€76.03 + VAT = €93.52** **V** (2026 tariff, APCMC/ECO 31.12.2025) | same day | inside the 20 working days |
| C | **DAV** (Declaração Aduaneira de Veículo) with uploads → **PT matrícula printed on it** | Online: Portal das Finanças → Serviços Aduaneiros → IEC/ISV → DAV → criar DAV (login: Portal credentials, CC or Chave Móvel Digital) | €0 (no state fee) **V** | 1–3 working days to validate **A** | **≤20 working days from entry** (CISV art. 20(1)(a)) **V** |
| D | Plates made with the assigned number; **PT insurance** on the new matrícula | Any plate shop; insurer | plates ~€20–40/pair **A** | minutes | before driving on PT plates |
| E | **IMT matrícula request**: Modelo 9 + ID + Modelo 112 + homologation + CoC + DAV + **original foreign registration** | **IMT counter or by post** (gov.pt lists no online channel; one commercial blog claims online) | **€45 with CoC/homologation, €165 without** **V** | — | original foreign registration **within 10 days of the DAV** (CISV art. 20(5)); request ≤60 days |
| F | **Registo inicial de propriedade** (IRN) → Certificado de Matrícula | Online at Automóvel Online (CC or qualified digital certificate) or any Conservatória/IRN counter | **€46.80 online / €55 counter**; doubled if late **V** ([IRN tariff](https://irn.justica.gov.pt/Custos-dos-servicos)) | days–weeks | ≤60 days |

### DAV facts **V** (CISV, Lei 22-A/2007, [consolidated text](https://info-aduaneiro.portaldasfinancas.gov.pt/pt/legislacao_aduaneira/codigos_aduaneiros/Documents/CISV.pdf))

- Art. 17(3): cars **excluded from ISV still need a DAV**. Art. 17(4): electronic only. Art. 17(5): max **3 DAVs per person per calendar year**.
- Uploads: foreign registration (all parts), **invoice or declaração de venda naming the buyer** (name, address, ideally NIF), CoC, homologation declaration, Modelo 112, and CMR + transport payment receipt if trucked. Keep originals 4 years (art. 20(4)); AT may demand them at any time.
- **The declarant is the acquirer**, so the contract/invoice must name the buyer — it is the DAV upload.
- Competent office: the alfândega for the buyer's district; any ISV-competent office is accepted (AT FAQ 10). No physical presentation at customs in the standard flow — the physical check is the CITV inspection.
- Entry on a temporary/transit plate that expires: entry is **presumed on the plate's expiry date** (art. 22(2)).
- After the DAV: payment proof with the matrícula noted allows unrestricted use for **60 days** (art. 22(4)).
- Late DAV: police notify the owner to file within 2 working days plus a coima (art. 22(1)); coima amounts (€250–2,500) come only from commercial blogs **A**.
- Keep proof of the entry date (CMR + receipt, or toll/charging receipts): it starts the 20-working-day clock.

### Driving in PT before PT plates (resident)

- Days 0 → DAV: driving on a **valid** foreign/transit plate with **valid insurance** is implicitly tolerated; the offence is not filing "atempadamente". **I** from CISV art. 22(1).
- After the DAV, until the ISV deadline: valid foreign plate + DAV copy carried + owner or spouse driving (art. 22(3), AT FAQ 12). **V**
- After the matrícula: fit PT plates; don't keep the foreign plates on (IMT/GNR position via press). **A**

## 3. Taxes

| | BEV | Non-BEV (ICE, hybrid, PHEV) |
|---|---|---|
| **ISV** (registration tax) | **Excluded from incidence** (not merely exempt): CISV art. 2(2)(a) "veículos exclusivamente eléctricos". OE2026 (Lei 73-A/2025) changed art. 8 (PHEV Euro 6e-bis rate) and art. 52 only — art. 2 untouched. **V** (AT Ofício-Circulado 25099/2026) | Due on the DAV; payment within 10 working days of liquidation (art. 27(1)) **V**. Amount depends on cylinder capacity, CO2 and age — use the official ISV simulator on Portal das Finanças before pricing a deal. **I** (rates not researched) |
| **IUC** (annual) | **€0**: CIUC art. 5(1)(e); no annual proof of exemption (art. 5(8)(c)); the OE2026 "adicional de IUC" inherits the exemption. **V** (CIUC ebook 08/2026) | Due yearly by CO2/cylinder capacity; the older-imports IUC debate concerns combustion cars. **I** — check AT's IUC simulator |
| **VAT** | Used (>6 months **and** >6,000 km): none in PT. New (either threshold not passed): PT IVA 23% assessed on the DAV, even from a private seller (RITI art. 1(1)(b), 6, 22; AT Inf. Vinculativa 15529). Date of first use = the registration document. **V** | same |

## 4. Fees and time (DIY, BEV)

| Item | € | Tag |
|---|---|---|
| Homologation declaration | 0 | V |
| Category B inspection | 93.52 | V |
| DAV | 0 | V |
| Plates | ~20–40 | A |
| IMT matrícula (with CoC) | 45 (165 without CoC) | V |
| IRN registration | 46.80 online / 55 counter | V |
| **Total DIY** | **≈ €205–215** + PT insurance | |
| Despachante (agent) | **+€250–500** on top of official fees (DAV-only ~€50–80) | A |
| Turnkey incl. transport | e.g. ~€2,600 quote for a French EV, Jul 2025 | A |

- **Time:** ~1–3 weeks to PT plates; ~3–6 weeks to the Certificado de Matrícula. **A** (blog estimates; no official SLA)
- **Pinch point:** inspection + homologation + DAV must fit inside the 20 working days from entry — and inside the transit plate's validity.

## 5. DIY vs despachante

- DIY is feasible for a private person: the DAV form auto-fills most fields once the homologation number is entered; with ISV €0 there is little to get wrong fiscally. **A** (forum, 2022)
- **A despachante cannot skip the inspection** (the car must be there; they can drive it, not avoid it). They can do the DAV, the IMT counter and the IRN.
- DIY in-person stops: the **inspection** (with the car) and the **IMT counter** (or post). Everything else online.

## 6. Accounts needed

| Account | For | Note |
|---|---|---|
| Portal das Finanças (NIF + password, CC or Chave Móvel Digital) | DAV, credenciação | V |
| IMT online | homologation declaration | V |
| Automóvel Online (IRN) | step F online | Needs a **Citizen Card (CC) or qualified digital certificate**. Residence-permit holders without a CC: unclear — fallback is the Conservatória counter (€55). **I** |

## 7. Documents — originals list

Bring/keep: foreign registration **all parts, originals** (registry keeps it at step E) · **CoC original** (saves €120 at IMT and carries the tyre sizes) · contract/invoice naming the buyer · Modelo 112 · DAV PDF · homologation declaration · CMR + transport receipt if trucked · seller-country de-registration proof where one exists (see the seller file).

## 8. Tyres and the CoC at legalisation

- Any tyre size listed in the **CoC** is legal even if the foreign registration lists only one (DE ZB I fields 15.1/15.2 show one size; the CoC lists all in field 32 or 50). **V** (ADAC)
- The PT registration document (DUA) has front/rear tyre fields; extra sizes go under "Anotações especiais" (Portaria 241-A/2019 **V**). Imported cars get their CoC sizes copied **A**.
- **At legalisation: hand over the original CoC and check the new DUA lists every size you will use** before leaving the counter. (EV run: an extra wheel set came in a size missing from the registration.)
- Periodic inspection (IPO) fails only for a size **not on the registration AND >5% outer-diameter difference**. **V** (inspection manual ITV-5, 2006 version). Fix if needed: an *averbamento* (~€30 IMT + ~€100 declaration) **A**.
- Mixing winter and summer tyres across axles is legal in PT (IPO fails only mixed types on one axle) **V**. But in DE winter conditions **all wheels need the snowflake mark** (§2(3a) StVO) **V** — drive home on a matched set.

## 9. Insurance gap

- EU Dir. 2009/103 art. 15 (amended 2021/2118) allows a PT insurer to cover the car **from acceptance of delivery for 30 days** by VIN/foreign plate. **V** (law). **No PT insurer product page confirms it** — forum reports of one insurer doing short policies on a German plate, commercial claims of 1–28-day policies on foreign plates, and other sources saying PT insurers cover only PT plates. **Treat 30-day cover by VIN as unverified** and use the seller-country transit insurance. **A**
- After the matrícula, PT insurance is mandatory — even inside the 60-day DAV window. **A** (press 12/2025)
- A PT insurer quoting the new policy asks for the **previous insurer's claims-history declaration** (no-claims) — get it before pickup. **A** (EV run 2026-11-07)

## 10. Buyer step list (PT side)

1. Before the trip: credenciação (if needed), homologation declaration online, **book the Category B inspection** ~4–10 days after arrival, check your Portal/IMT/IRN logins.
2. Make sure the transit plate + insurance run ≥ drive + inspection (≈30 days).
   At pickup (details in [../buy/pickup-day.md](../buy/pickup-day.md)): ask the dealer to run pending OTA updates and campaigns before handover; become primary user in the brand app with the previous owner removed; collect the previous insurer's claims-history declaration. (EV run 2026-11-07)
3. Arrival: keep entry-date proof. 20-working-day clock starts.
4. Inspection at the buyer's nearest Category B inspection centre → Modelo 112.
5. DAV online → PT plate number.
6. Plates + PT insurance (claims-history declaration ready).
7. IMT counter or post, original foreign registration + CoC, within 10 days of the DAV; check tyre sizes on the new DUA.
8. IRN registration (online or counter) within 60 days.

## Open questions

1. Does a PT insurer sell the 30-day art. 15 cover by VIN/foreign plate? (would replace seller-country temporary insurance)
2. Automóvel Online login for non-CC residents.
3. Is SFA2 credenciação needed for individuals?
4. Is the IMT step E counter/post only (official) or also online (one commercial claim)?
5. Does the DAV/IMT strictly require the Spanish baja document? (see [es-to-pt.md](es-to-pt.md))
6. Processing times and the late-DAV coima amount are unofficial.
