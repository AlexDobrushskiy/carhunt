# Shutdown (deal signed → hunt closed)

> Snapshot: researched Oct–Nov 2026. Prices, laws and tool behaviour drift — re-check anything you act on.

Siblings: [contract-checklist.md](contract-checklist.md) · [pickup-day.md](pickup-day.md) · [deposit-payment.md](deposit-payment.md)

WHY this exists: once a contract is signed, dozens of chats are left ending on an inbound message, replies go stale across agent handovers, and paid services keep running. The plan: stop sweeps on signing, keep backups warm until the car is in hand, then one thanks/close line to every open chat.

## 1. On signing (contract sent back)

| Step | How |
|---|---|
| Freeze new contacts | `carhunt pause` (writes `$CARHUNT_HOME/PAUSE`; `carhunt say` refuses openers). Polite replies only from here |
| Stop discovery | Disable the daily sweep: remove its job from `orchestrate.schedule` and re-run `carhunt schedule install` (or `launchctl bootout` the job); close the sweep session |
| Stop idle agents | Close outreach agents that have no backup chat; keep one agent (or the WhatsApp/email watcher) for the backups |
| Unanswered list | List every chat ending on an inbound message; reply or close each (§3). Do this at every handover too |
| Pick backups | Keep **1–2** strongest alternatives warm until pickup is done (a backup costs nothing) |

## 2. Keeping backups warm

- Honest holding line: *"I'm closing another option; I'll tell you in a few days."* A seller's "otherwise I sell to a dealer" is a pressure line — this answer usually gets "OK, I'll wait".
- No promises, no price talk, no viewing dates. If a backup sells meanwhile, fine.
- Release backups (thanks/close line) once the car is picked up and the lift check passed ([pickup-day.md](pickup-day.md)) — or keep one until the DE withdrawal window is clearly not needed.

## 3. Polite close (short, no names, seller's language)

| Lang | Text |
|---|---|
| EN | Thank you for your time and answers. I've bought another car, so I'm no longer looking. Good luck with the sale! |
| DE | Vielen Dank für Ihre Zeit und Antworten. Ich habe inzwischen ein anderes Auto gekauft und suche nicht mehr. Viel Erfolg beim Verkauf! |
| PT | Muito obrigado pelo seu tempo e pelas respostas. Entretanto comprei outro carro, por isso já não estou à procura. Boa sorte com a venda! |
| ES | Muchas gracias por su tiempo y sus respuestas. Ya he comprado otro coche, así que ya no busco. ¡Suerte con la venta! |
| FR | Merci beaucoup pour votre temps et vos réponses. J'ai acheté une autre voiture entre-temps, je ne cherche donc plus. Bonne chance pour la vente ! |

- Send to every chat still open (talking/contacted with a reply). Not to sellers who never answered, not to closed chats.
- Respect the channel's spacing/caps and quiet hours (`carhunt say` enforces them). Check with `carhunt say --dry-run` whether PAUSE also refuses replies; if it does, unpause only for the close batch, then `carhunt pause` again.
- Chats the owner handles himself (his own messages not in the send ledger) — stay out.

## 4. Archive

- Archive the chats in each app (WhatsApp, portal inboxes, email label) after the close line.
- cardb: bought car → `cardb status CAR bought`; every other active car → `cardb status CAR closed --reason "bought another"` (dropped cars stay `dropped`); verdicts left as-is (history). `cardb backup DEST` once.
- Agent state: each agent's `state.json` → `status completed`, open threads empty.

## 5. Cancel everything that renews

| Item | Action |
|---|---|
| Residential proxy plan | Cancel / switch off auto-renew; delete the stored secret |
| SMS rental numbers | Release numbers; cancel any subscription |
| VIN/history report subscriptions & trials | Cancel. EpicVIN's $1 trial auto-renews at $99.99/month (**A**); pack credits (carVertical ~6 months, CARFAX ~4 years) don't renew — note the expiry |
| Paid decoders / captcha solver balance | Cancel auto top-up |
| Portal premium/alerts | Turn off saved-search emails and paid boosts |
| Site accounts created for the hunt | Keep (logins) or delete — owner decides; never leave plaintext credentials anywhere |
| Browsers | All lanes/identity closed; reaper confirms none left |
| Scheduled jobs | `launchctl list | grep carhunt` empty (except what you deliberately kept) |

## 6. Learning pass

- Run `carhunt learn` once more: lessons from the closing days (contract, payment, pickup) go back into these knowledge files and role briefs.
- Record the final verdict + what made the bought car win in cardb (`cardb note CAR "…" --pin`), so next time's search criteria start from it.
