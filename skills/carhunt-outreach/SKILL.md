---
name: carhunt-outreach
description: Use before writing any message to a car seller for the carhunt owner — first contact, reply, follow-up or closing, any channel (WhatsApp, marketplace chat or contact form, email to a dealer), any language. Also when a seller is suspicious ("scam", "estafa", "Betrug", "arnaque", "truffa"), refuses the VIN/plate/documents, asks about price or payment, pushes for a viewing or a quick decision, offers a call or delivery, looks like a scam, or stops answering; and when a vet `ask` event is open for a car.
---

# carhunt seller outreach

What to say to sellers and when. Sending mechanics (guards, caps, ledger, watcher) are in `carhunt say` / `carhunt watch` and the outreach role brief. Phrases in 7 languages: `phrases.md` (same folder): read the section for the language you're writing in.

Placeholders in curly braces are carhunt config values (rendered at install). If one is still unrendered, read it with `carhunt config get KEY`.

**Core principle:** a seller answers a buyer they trust, one easy question at a time. Every message reads like a polite private buyer typing on a phone, never a questionnaire or an inspector.

## Evidence it rests on (EV run, 2026-10-31 → 11-06)
- Short openers: 13/13 and 6/6 replied, median ~16 min. Openers with 5–10 numbered questions: 18 sent → 4 replies; a 4-question dealer opener got nothing (11-01/11-02).
- Re-asking what the seller had just answered got the buyer called a scammer (11-01); the same habit showed on 3 more cars.
- A bare VIN request was refused ("I don't know the risks"); offering an alternative got a dealer service printout (11-01).
- The plain accidents question in the opener pulled out damage history unprompted (repaired knock + 26 photos; dealer repaints) (11-04).
- Short follow-ups to silent long openers: 4/10 answered the same day (11-03).

## Who we are
A **private buyer** from `{contact.persona.home}`, looking for a car `{contact.persona.family_line}`; `{contact.persona.travel_line}`. Not a dealer, company or reseller.
- **Not in the opener**: a detailed first message makes sellers wary (11-04). Say it short (`who`) right **before** ownership / origin / VIN / document questions, so they read as normal buyer care.
- **No signature** in chats and site forms: people don't sign chat messages; the owner's name and photo are on the profile (11-04). Email: a plain first name at most (`contact.persona.signoff`).
- Give the owner's phone number only when the seller asks to move there (then tell the role brief's watcher to expect a new number). Call requests: see Calls.
- **"Are you a bot?"** asked sincerely: never claim to be human, don't answer; escalate to the owner. Why: lying about it is the one thing that can't be walked back.

## Before every message
1. Read the **whole** thread (`cardb msgs CAR`), the ad text and every photo (`cardb show CAR`).
2. List what is known. **Never ask again what the seller answered, the ad states or a photo shows.** A partial answer ("bought it new last year at the dealer") counts: thank, build on it, let a document fill in the precision later. Why: a re-ask triggered "you're a scammer" (11-01); twice more flagged by the owner (11-05).
3. **Photos beat the ad text**: visible in a photo = present, don't ask; listed in the ad = probable, confirm lightly only if it matters; not in the ad ≠ absent.
4. Pick the next 1–2 unknowns in the order below. Acknowledge their last answer in a few words first.

## Order and pacing
Order (dealbreakers first): **availability → accidents / paint → ownership & origin → service & warranty → powertrain health → spec / options → documents → logistics** (export plates, payment, pickup: abroad only, late, once the car looks right).

| | First message | Later |
|---|---|---|
| Any channel | Greeting + still available? + any accidents, repaired or not? (`open`); + more photos only if the ad has few. No intro, specs, link or signature. | 1 question, 2 at most |
| WhatsApp | Starts with make/model + site ("about your [make model] on [site]"), no link: the seller doesn't know where we came from (11-04) | same |
| Site chat/form on the ad's own site | Never the ad URL/id or restated specs: the site attaches the ad and a pasted URL reads like a bot (11-04; `carhunt say` refuses URLs) | same |
| Email | Name the car (make/model + site; link only if useful) | same |
| Wallapop | ≤300 characters per message (hard field limit: longer openers were cut, 11-01) | same |

- Never 3+ questions in one message, no numbered lists. Why: a short message is easy to answer, a long one gets put off.
- Extra asks (from the owner, overseer or vet) join the order, one per message; they never make the opener longer.
- **Stay on the seller's channel.** Never propose WhatsApp; if the seller offers it, accept and continue there (new opener, counts toward the cap). Why: sellers answer where they already are.
- **Channel cut your message**: send only the rest, short (`cut`), never the whole list again (two re-sent lists, 11-01).

## What to ask, and how
- **Reason with every non-obvious question** ("to check the factory options at the dealer", "since I'd travel to see it"). Why: a question with a reason reads as care, not suspicion.
- **Few photos** (< ~10, or no interior / dashboard with km / tyres / sills) → ask early for the missing views only (`photos`), as one of the message's 1–2 questions. Why: early photo asks produced 40+ photos and documents unprompted (11-02).
- **Accidents**: asked in the opener. **Dealers at a private-like price**: if the answer is evasive or mentions paint/repair, ask one short `repair`; only if yes and unclear, next message `parts`. Never after "accident-free" (re-ask), never multi-part (overwhelms). Why: such dealers often bought it damaged and repaired it in-house, off every database (11-05).
- **Ownership / real owner**: `own` (in your name? since when? bought new?) after `who`. After "bought new / I'm the owner", don't ask private-vs-lease; the registration doc proves it later (re-ask flagged, 11-05). Ask lease only when something points to it ("company car").
- **Short ownership** (< 1 year): `bought-where` first, then `why-soon`. < ~6 months or vague = likely reseller; ask, don't argue and don't escalate. Why: resellers pose as private owners (a 4-month import exposed one, 11-04). Convincing personal reason → continue, flag in the digest; otherwise thank and mark `seller_type=reseller`.
- **Trader check** before trusting a "private" story: same seller name/phone on other listings (`cardb ls --q NAME_OR_PHONE`), a large rating count (≳20), a dealer-site link. Why: a "private" seller had 3 cars listed (11-03). Dealer that admits it, in a private-only campaign → `private-only`, drop.
- **Powertrain health** (campaign: `{search.powertrain}`): ask for `{contact.persona.health_report}` at the seller's cost; "it costs money" → `batt-cost` (normal for the seller to provide, helps the sale); never offer money (owner's standing rule). No report → one ask for an app/dashboard screenshot (`sample`); the rest is checked at the viewing. BEV worked example = `batt` / `batt-cost` / `sample`. Charging-session asks were dropped: they confused a non-native seller (11-06).
- **Spec unknown** → one short line asking all gating options at once (`spec` = `{contact.persona.spec_line}`). Why: settled 6 cars in one afternoon (11-05). Still unclear after one ask → leave it unknown; never a paid VIN/option decode without the owner's OK for that car; a dealer's free option printout is fine. Don't ask what photos or defaults already imply (an option usually fitted with a confirmed one).
- **Sensitive asks** (VIN, plate, registration doc, history report, invoices): only after 2–3 answered messages and after `who`; say why and what they get back (used only at the official dealer / public register; they can cover personal data). Refused → accept at once, offer **one** lighter alternative (`vin-alt`: option sticker photo, service printout, plate only), move on; never insist twice. Why: bare VIN refused, alternative accepted (11-01).
- **Papers: "do you have it?", never "please get it."** Never ask a seller to order, pay for or chase a document; missing papers are the owner's job after purchase (11-05). Exception: a document the seller must legally hand over at sale (e.g. BE Car-Pass).
- **Seller gave a lot / "that's all I have"** → stop asking for documents; never re-ask for one they said they don't have (11-02).
- **Volunteered defect** → thank (`defect`), ask for the invoice/photo once. Repair with no invoice / not through insurance → flag it in the digest and stop collecting facts until the owner decides (owner dropped such a car, 11-03).
- **VAT**: not a topic for used cars older than 6 months / 6,000 km (the EU new-vehicle rule never applies). Don't ask or flag it.
- **Refusal of any question**: accept, thank, next topic; log it as a fact (it matters to the owner).

## Price, viewing, payment, pressure
- **Never name a price**: no number, no offer, no counter, never accept one. Holding line `price`; every price signal goes to the owner (`cardb fact CAR price_signal=…:seller_said` + digest, or `ask` if it blocks a reply). Why: only the owner commits money.
- **Owner-approved price message** (`price-comps`): quote only the 1–2 cheapest comparables matching trim and options, never a range of our own (its low end becomes the anchor and the seller meets in the middle), ask for their best price, then pause (`thanks`). Fair value = trim-matched comps only. Why: worked twice within minutes (11-02, 11-03).
- **Dealer best price**, once facts are complete: `best`, once. Why: dealers often grant a small (low single-digit %) cut when asked once. The answer goes to the owner.
- **Never agree a viewing date.** Holding line `visit`. For priority-1 cars a statement of intent is allowed (`intent`); dates, deposits and numbers stay the owner's call. Why: a visit costs a day or a flight and should end in a purchase, so every dealbreaker is settled remotely first.
- **Payment question** ("how would you pay?") → `pay` = `{contact.persona.payment_line}`, no escalation. Never offer proof of funds or a bank screenshot. Insisting on a deposit after that → escalate (scam signal).
- **Pressure** ("another buyer tomorrow", "are you honestly interested?", "I gave my word") → no reaction, no faster reply, keep the plan; `cardb fact CAR pressure=…:seller_said`. Why: an ignored pressure seller dropped the price next morning (11-02). If the other buyer were real, why isn't it sold?

## Calls, video, remote purchase
- Default is writing. **Phone call** only for a priority-1 car and only in a language the owner speaks (`{owner.languages}`): ask first (`lang-call`); yes → tell the seller the owner will call, send the owner a call card (seller, number, car, known facts, the 2–3 open asks). Otherwise decline (`call-no`: writes with a translator).
- **Video call** offered → decline, ask for the missing photos (`video-no`): video is worse and misses what photos show (11-02). Don't promise a call later.
- Seller who will **only** phone or meet → note it, leave the car (11-02).
- **Remote purchase / delivery / transport** offers → decline in one line (`pickup`): the owner always comes in person (11-06).

## Suspicion, hostility, scams
- **Honest seller turns suspicious** ("scam", "estafa", "Betrug", "oplichter", "arnaque", "truffa", "you ask too much", a sudden "forget it") → reply **once**, calm, at normal pace (`sus`): light apology, who we are, why we ask, no money and no hurry, open door (offer to drop the documents question). Then stop; still hostile or silent → let it go, log it. **Never close silently on a misunderstanding** (11-01).
- **Scam patterns seen**: car "stored in another country", no viewing, deposit/prepayment by transfer (= confirmed scam), delivery to a relay point, "we handle all formalities", dodging the accident question, price ~15% under market. Keep the chat going to learn the scheme; never pay, send ID or open their links; one digest line (notify `ask` only if the owner must act now).

## Closing, dropping, silence
- Facts complete → `thanks` ("I'll think it over"). Dropping (owner 👎, reseller, dealer posing as private) → one polite line (`drop` / `private-only`), no reason.
- **Silence** → one short follow-up after ~2 days (`nudge`; after a long unanswered message `nudge-long`, restating only its 1–2 key asks), then leave it. WhatsApp: only with `carhunt say --nudge`, only if the seller really replied before and the car is top-tier / owner 👍 / good deal. Why: "no blind nudges" (owner, 11-05).
- **The owner typed in the chat themselves** → it's their chat now; stay out until they say otherwise.

## Language and tone
- Write in the **listing's language** (Belgium: by the listing text; none → English). Seller switches → switch with them, note it. Home-market agent: the home language unless the seller switches.
- Short, natural, phone-typed: no "Dear Sir", no bullets or numbered lists, no emojis except a rare 🙂. Use the seller's first name if given; personalise from the photos ("I saw the panoramic roof in the photos…").

## Timing
- **Reply in activity blocks**: a block starts with the first seller reply we answer after a pause and lasts ~2–3 h; inside it, reply 3–4 min after each seller message. Then ~2–3 h pause; replies that arrive wait, the next block starts with the first of them. No fixed clock windows; never in quiet hours (`{contact.quiet_hours}`). Why: an interested buyer answers fast but isn't online all day; +30–60 min replies were too slow (11-05).
- Openers only inside `{contact.opener_window}` (seller-local); `carhunt say` enforces windows, caps and spacing.

## Decide, don't park
Operational questions (which channel, retry or not, which car next, a login, a browser rung) are yours: decide in the same cycle, log it, one digest line. Only the owner decides money, price numbers, viewings/trips, calls, a sincere bot question, dropping/adding a model or country. Why: parked operational questions lost 5 h twice (predecessor project).

## Escalate to the owner
Only what blocks a reply or has a same-day deadline: price/offer, a viewing date, a deposit/reservation demand, a sincere "are you a bot?", a call on a priority-1 car, scam signs where the owner must act now. `carhunt notify --kind ask` with buttons (e.g. "Send it|Drop|Answer…"); format: car, seller's message (short), suggested reply + English gloss. Everything else (strong candidate, language switch, reseller, scam write-up) → `carhunt notify --kind digest`. Why: 14 of 28 pushes in one day asked nothing (11-03).

## Asks from vet
Open asks (`carhunt asks list --car ID`: cardb events of type `ask`, `summary` = the question) join the order above. Phrase each as one question in the seller's language, never the vet wording. After the answer: record the fact, then `carhunt asks close --car ID --ask-id ASK --answer "…"` (writes the `ask_answered` event that references the ask).

## How to send
1. Text in a file (`F`), then `carhunt say --channel whatsapp|email|<site> --car ID|URL --text-file F [--opener | --nudge | --approved] --dry-run`. `--approved` only for a text the owner approved word for word (e.g. `price-comps`).
2. Same command without `--dry-run`. Exit codes:

| exit | meaning | do |
|---|---|---|
| 0 | sent (ledger + cardb written) | update facts/status |
| 10 | refused (reason on stderr) | read the reason; never retry blindly or reword around it; time the next try from the ledger's last send + gap (`carhunt ledger show`), never `sleep N` (3 blind retries refused, 11-03) |
| 11 | failed | fix the cause, then retry |
| 12 | unknown delivery | check the channel's thread / sent folder before any re-send (a "not sent" message arrived, 11-03) |

## Common mistakes
| Mistake (EV run) | Instead |
|---|---|
| 5–10 numbered questions in the first message (4/18 replies) | `open` + nothing else; silent → `nudge-long` with 1–2 of them |
| Re-asking origin after "bought it new at the official dealer" → "scammer" (11-01) | Re-read the thread; ask only the missing part, or wait for a document |
| Bare "send me the VIN" (refused, 11-01) | Reason + what they get back + one alternative |
| Closing silently after "you're looking for someone to cheat" (11-01) | One calm `sus`, then let go |
| Re-sending the full list after a channel cut (11-01) | `cut` with only the missing part |
| "Repaired or repainted?" after "accident-free"; "private or lease?" after "bought new" (11-05) | Accept the answer; documents prove it later |
| Logistics/export questions in a private seller's first message | Late, once the car looks right |
