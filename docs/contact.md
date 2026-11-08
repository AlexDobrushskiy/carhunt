# contact

Talk to sellers without getting banned, double-messaging or leaking: every message goes through `carhunt say`; every inbound message comes in through `carhunt watch`. Code: `carhunt/contact/`. Skill: `skills/carhunt-outreach/` (what to say). Role brief: `agents/roles/outreach/brief.md`.

## Commands

| command | does | exit |
|---|---|---|
| `carhunt say --channel C (--car ID\|URL) [--to ADDR] (--text T\|--text-file F\|-) [--opener\|--nudge\|--approved] [--dry-run] [--json]` | one flock: guard → send → verify → ledger; then cardb `msg` (dedupe key = ledger id) | 0 sent · 10 refused (reason on stderr) · 11 failed · 12 unknown delivery |
| `carhunt watch [--channels a,b] [--once\|--until-new] [--interval 60] [--agent ROLE]` | new seller messages → cardb (verbatim) + `$CARHUNT_HOME/agents/ROLE/inbox.jsonl` + one JSON line on stdout | 0 · 2 if stdout is /dev/null |
| `carhunt mailroute [--window 3d] [--dry-run] [--filters] [--launchd]` | car mail out of the inbox by address/domain/thread; Gmail filter XML; launchd plist | 0 |
| `carhunt ledger [show\|reconcile] [--limit N] [--since T]` | show sends; re-post every row to cardb (idempotent) | 0 |
| `carhunt asks [list\|close] [--car ID] [--ask-id E \| --topic T] [--answer A] [--no-fact]` | open vet/buy asks (cars in to_contact…visited); close one with `ask_answered` | 0 · 1 nothing open · 2 usage |

- `--to` defaults to the car's contact for that channel (WhatsApp/phone, email, or the car's live listing URL on that site).
- `--dry-run` reads only local sources (wacli's local DB, cardb), prints the guard decision and the would-send payload. Nothing leaves the machine.
- Exit 10: read the reason, fix or wait. Time the next send from the ledger (`carhunt ledger`), never `sleep N` (a blind retry is refused again).
- Asks (vet ↔ outreach contract): an `ask` event carries `data.topic` + `data.fact`. Fold it into your next message (one question per message), then `carhunt asks close --car C --topic T --answer "<what the seller said>"` (or `"refused: …"`). Close writes `ask_answered` with `data {ask_event, topic}` and fills the ask's fact (source `seller_said`) unless the car already has a real value. Why: vet decides "have" from facts; a close without the fact = vet re-asks, and a re-ask got us called scammers (11-01).
- Exit 12: the message may have gone out. Check the channel (chat, Sent folder) before any re-send (network errors can hide a delivered message).

## Guard rules (order) and why

| # | rule | why |
|---|---|---|
| 1 | mode: `--nudge` alone; `--opener` and `--approved` exclusive | different rule sets |
| 2 | `$CARHUNT_HOME/PAUSE` → refuse | night pause / owner freeze; re-checked inside the lock right before each send (a chain may start just before a freeze) |
| 3 | caller: if `CARHUNT_AGENT`/`CARDB_AUTHOR` is set, `AGTERM_SESSION_ID` must equal that role's `state.json` `active_agent` | background chains must stop sending after a handover |
| 4 | target: car exists in cardb, status not dropped/closed/bought (unless `--approved`), `--to` is one of its seller contacts or listing URLs (shared call-centre numbers excluded) | same car under several URLs; sold ads; traders |
| 5 | text: 1..max_len (WhatsApp 500, Wallapop 300…); site channels refuse URLs | long texts get cut; the site attaches the ad, a link reads like a bot |
| 6 | opener text: no URL, no specs (km/kWh/hp/€), ≤ 280 chars, ≤ 2 questions | short openers get replies, long ones mostly don't |
| 7 | quiet hours (owner tz) | nobody answers at night; night sends look like a bot |
| 8 | limits over the shared ledger (below) | WhatsApp bans bursts to new contacts; one budget for all agents |
| 9a | opener: no earlier message from us/owner in thread or ledger; seller-local opener window | first message must be first |
| 9b | reply: thread not empty; last message not ours unless `--approved`; seller's message ≥ 3 min old; owner didn't write in the last 15 min (a FromMe message not in the ledger) | double messages read as pushy; instant replies read as a bot; owner's own chat |
| 9c | nudge: thread readable; last is ours and ≥ 48 h old; seller really replied before (not a reaction, not < 15 s after ours); one nudge per thread; no `--approved` send; no price talk; no no/sold; owner never wrote himself; car status nudgeable; car matches a `nudge.qualify` predicate and no `nudge.exclude`; seller-local business hours | no blind nudges; a short follow-up to a silent long opener often gets an answer |
| 10 | seller-local business hours for channels with `seller_hours: true` (default: email) — dealer or private profile from the car's seller type | dealers answer in office hours |
| 11 | duplicate: first 60 chars already sent to this target (ledger or thread) | a retried opener must not go out twice |

After the guard: send → `verify` (delivered / failed / unknown) → ledger row → cardb. A failed attempt does not count for spacing; unknown counts (it may have gone out).

### Limits (`contact.limits`)
Each limit: `name`, `channels` (list of names, `sites` = every site channel, or `*`), `kind` (`opener|nudge|any`), `per_channel`, and `min_gap_s` and/or `per: hour|day` + `max`, optional `reserve {role, slots, until}`. Day = owner-tz calendar day. One-day override: `$CARHUNT_HOME/contact/cap_override.json` `{"date": "YYYY-MM-DD", "limits": {"openers-daily": 25}}`.

| default limit | value | why |
|---|---|---|
| chat-spacing | WhatsApp + site chats ≥ 180 s apart | ban risk on the owner's number |
| chat-hourly | ≤ 12 / hour | same |
| openers-daily | ≤ 20 / day, all channels; last 4 slots reserved for `outreach-home` until 15:00 | ramped 6 → 20 over 4 days; abroad sends used to bypass the cap |
| opener-spacing | ≥ 10 min between openers | bursts of cold contacts |
| email-spacing | ≥ 5 min | dealer mail servers + spam filters |
| site-spacing | each site ≥ 10 min (per channel) | site anti-bot pacing |
| followups-daily | ≤ 15 nudges / day | follow-ups are pushy at volume |

### Nudge predicates (`contact.nudge`)
`qualify` (any must match) and `exclude` (none may match) are lists of predicates over the cardb car: `{field, eq|ne|in|not_in|between|gte|lte|truthy}`, combinable with `{all: […]}` / `{any: […]}`, optional `why` (shown in the refusal). Dotted fields (`verdict.value`, `seller.type`); computed `power_hp`. Defaults: tier 1, owner 👍, or good deal. Example exclude (EV run: these went quiet even with a 👍):
```yaml
exclude:
  - {field: model_family, in: [BMW iX1, Mercedes EQB, Toyota bZ4X], why: "goes quiet even with a thumbs-up"}
  - {all: [{field: model_family, in: [VW ID.4, Audi Q4, Skoda Enyaq]}, {field: power_hp, between: [195, 210]}], why: "204 hp variant goes quiet"}
```

## Ledger
`$CARHUNT_HOME/contact/ledger.jsonl`, one row per send attempt, all channels and agents: `id, t, channel, to, car, kind (opener|reply|nudge|approved), status (sent|failed|unknown), by, text, err, external_id`. Appended inside the send lock with `O_APPEND` + fsync. It is the only send log. cardb gets every row at once with `dedupe_key = id`; a cardb failure never blocks or retries the send; `carhunt ledger reconcile` backfills.

## Watcher
- Channels: `contact.watch.channels` (default `[whatsapp, email]`) + site inboxes that have a `poll` (Wallapop has no email alerts: without its own poll replies are seen hours late).
- One cursor store `$CARHUNT_HOME/contact/cursors.json` (per channel: `since` + recent ids), 5-min overlap, advanced only after the message is logged (so a reply is never skipped as "our own send").
- Skips our own messages, reactions, empty edit/delete stubs (wacli shows protocolMessages as new).
- Unknown number (seller writes from a new phone): still goes to the agent inbox with `cardb_error`; the agent attaches it to the car.
- Run it as a tracked background task, never `&`, never with stdout to /dev/null (it refuses); re-arm on any non-zero exit (e.g. killed by a terminal restart).

## Channel matrix
| channel | send | verify (delivered when…) | read thread / poll | route · country · max_len | notes (why) |
|---|---|---|---|---|---|
| whatsapp | wacli `send text` | wacli returned a message id, or our text is in the local chat | wacli local DB · `messages list --from-them --after` | — · — · 500 | ban risk; "no LID found" = not on WhatsApp → site chat; groups refused |
| email | Gmail API, Reply-To plus-address, threaded | message found in Sent by Message-ID | thread by address/`#THREAD` · `after:<epoch>` on label/plus-address | — · — · 4000 | dealer email gets replies where AutoScout24 forms fail; group mailboxes bounce → use the named salesperson |
| mobile.de | ad form / conversation reply | "Anfrage erfolgreich gesendet" | conversation · (replies come as relay mail → email watcher) | identity · — · 500 | contacted ad has no form → reply in the conversation |
| autoscout24 | guest contact form (persona name/email) | locale success text or `afterlead` URL | — | lane · — · 500 | .de/.nl forms unreliable → refused unless `force`; prefer dealer email |
| kleinanzeigen.de | ad chat | our text in the thread, box cleared | thread | identity · — · 500 | success wording never seen in a log |
| subito.it | ad chat / thread reply | our text in the thread | thread · inbox poll | identity · — · 500 | removed ads keep their thread: reply inside it |
| leboncoin.fr | `/reply/<id>` | our text in the conversation | conversation · inbox poll | plain-chrome · FR · 2500 | account needs a FR IP; stop at the first 403; never "Faire une offre"; gone (404/410) ≠ blocked |
| wallapop.com | chat | our text in the chat | chat · own poll (no alert mail) | identity · — · 300 | handles "send personal data?" + onboarding modals; cut message → send only the cut part |
| coches.net | contact POST | site's 2xx to the contact POST (403 = failed) | — (replies = Gmail relay mail) | camoufox · ES · 500 | Imperva flags Playwright for hours; only the stealth browser on an ES residential proxy worked |
| standvirtual.com | "Mensagem" chat panel | our text in the thread | thread on the ad URL | identity · — · 500 | |
| olx.pt | chat | our text in the thread (send selectors unverified) | thread | identity · — · 500 | first real send = verify end to end |
| custojusto.pt | one-way ad form, then Sendbird chat | "contactado com sucesso" / text in chat | chat · inbox poll | identity · — · 500 | the ad form is one-way; the reply shows in the site inbox only when the seller answers |

Not shipped: marktplaats.nl / 2dehands (no sender ever worked; messaging needs a phone 2FA step). A sender counts as working only after one real send is verified end to end (a script can report success and deliver nothing). Every site sender: no URL in the text, duplicate guard on the first 60 chars of the thread, `unknown` (exit 12) when no site confirmation is seen.

## Setup

### WhatsApp (wacli) — optional, ban risk
- `brew install openclaw/tap/wacli`; pair as a linked device: `WACLI_READONLY=0 wacli auth` → phone: WhatsApp → Linked devices → Link a device → scan the QR (phone-number pairing codes can fail on passkey accounts).
- Keep a sync running: launchd `wacli sync --follow --presence-mode quiet` (quiet = the phone keeps its notifications). Unlinked after ~14 days offline → re-pair by QR.
- Agents read with `WACLI_READONLY=1` (set it in the agent env); only `carhunt say` lifts it for one send. `carhunt hooks install` (orchestrate) adds the PreToolUse guard that blocks any other wacli write.
- Never touch wacli's store/session files; only the CLI.
- **Risk:** unofficial clients breach WhatsApp's ToS. Bans hit spam-shaped behaviour (bulk/fast sends to cold contacts, new numbers). Consequence: WhatsApp on your main number banned (appealable). That is why the limits above exist; don't raise them casually.
- `send` error "no LID found" = number not on WhatsApp → use the site's chat.

### Gmail (email channel + mailroute)
- **OAuth client**: Google Cloud console → new project → enable the Gmail API → OAuth consent screen (External) → **publish to "In production"** (in "Testing" the refresh token dies after 7 days; an unverified personal app is fine, you click through the warning once) → Credentials → OAuth client ID, type *Desktop app* → download the JSON → `carhunt secret set gmail_oauth_client < client.json`.
- **Token**: one-time loopback consent (`carhunt.contact.gmail.local_consent`, scope `https://www.googleapis.com/auth/gmail.modify` = read, send, label; no delete) → store the token JSON with `carhunt secret set gmail_token`. 401 → the client refreshes once; a revoked token needs a new consent.
- **Plus-address**: outgoing car mail sets `Reply-To: you+<plus_tag>@domain`, so seller replies are recognisable even when they hit the inbox; From stays your normal address.
- **Filters**: `carhunt mailroute --filters > filters.xml` → Gmail → Settings → Filters → Import (marketplace + dealer domains + `to:` plus-address → label, skip inbox). The API can't create filters without the `gmail.settings.basic` scope (and a fresh "verify it's you"), so import by hand once.
- **Router**: `carhunt mailroute --launchd > ~/Library/LaunchAgents/com.carhunt.mailroute.plist` (every 3 min, 3-day window) and `--launchd --deep` (daily 60-day pass) → `launchctl bootstrap gui/$(id -u) <plist>`. It moves threads by known address / domain / thread only — never by words; freemail domains match by full address only; `never_touch` wins over everything; it never marks read or deletes.
- Gmail search rules baked in: never `in:inbox` (car mail is moved out of it), `after:<epoch>` (no minutes unit in `newer_than:`), times are UTC.
- Email `--to` forms: `addr` (replies into the latest thread with that address, else new thread: needs `--subject`), `addr#THREAD`, `#THREAD`. Errors before the request are retried ×3; after it, Sent is checked by Message-ID, never re-sent.

## Config (`contact:`)
Keys and example values: [`config.example.yaml`](../config.example.yaml) `contact:`; every key has a default (`carhunt/contact/settings.py`), so set only what differs. Home vs abroad is the role name (`outreach-home` | `outreach-abroad`, picked at launch), not a config key. `contact.sites.<site>.selectors` pins a sender selector (msg_sel, mine_sel, box, conv_sel…) without a code change.

Site forms never get a phone number (phone fields are emptied before submit).

**`contact.channels` as a plain list** (`[whatsapp, email, sites]`) = the channels allowed to send: `say` refuses any other (exit 10, rule `channel`; `sites` = every site channel), and `watch` polls that list (minus `sites`) when `watch.channels` is unset. The mapping form above only tunes channels and allows all. Why: a list that enforced nothing let a channel the owner left out still send.

Other keys contact reads (defaults in `carhunt/contact/settings.py`, example values in `config.example.yaml`):

| key | what |
|---|---|
| `blocked_statuses` | car statuses `say` refuses (default dropped, closed, bought); `--approved` overrides |
| `require_active_agent` | caller's `AGTERM_SESSION_ID` must be its role's `active_agent` (default true) |
| `duplicate_prefix` | refuse a text whose first N chars were already sent to this target (default 60) |
| `allow_unlisted` | allow `--to` that isn't one of the seller's cardb contacts (default false) |
| `opener.spec_pattern` | regex of specs refused in openers (km/kWh/kW/hp/€) |
| `nudge.auto_reply_s` | a "reply" this soon after ours is an auto-greeting, not a human (default 15) |
| `nudge.seller_hours` | which `seller_hours` profile nudges use (default dealer) |
| `nudge.price_extra` / `nudge.no_extra` | extra regex alternatives for price talk / "no, sold" detection |
| `phone_tz` / `country_tz` | dial prefix / ISO-2 → seller tz (seller-local windows); unknown → refused |
| `whatsapp.wacli` | wacli binary path (env `CARHUNT_WACLI` wins; else PATH) |
| `email.sent_label` | Gmail label put on our sent mail (default `email.label`) |
| `email.verify_tries` / `email.verify_wait_s` | Sent-folder check after a send (default 3 × 5 s) |
| `email.poll_overlap_s` / `email.poll_ignore` / `email.poll_limit` | watcher: re-read window (900 s), From substrings to skip, max messages per poll (200) |
| `mailroute.addresses` | extra seller addresses always routed out of the inbox |
| `mailroute.deep_at` | local time of the daily 60-day pass (default 04:10) |

## Gaps
- Site thread/inbox selectors on mobile.de, kleinanzeigen, subito, wallapop, leboncoin, standvirtual and the OLX send box / CustoJusto ad form are unverified live: the first real read per site must confirm them, then pin them under `contact.sites.<site>.selectors`.
- Routes per site: leboncoin = its own profile on a FR exit (never the identity pool); coches.net = Camoufox with main-world eval; mobile.de/subito/kleinanzeigen = plain-chrome on an identity profile; CustoJusto/OLX logins live on the identity master.
- Wallapop sends need the item id or chat URL (an `/item/` URL costs one extra page load); mobile.de already-contacted ads have no form → reply via the seller's relay mail.
- Site send results carry flags (`blocked`, `login`, `gone`, `no_form`, `already_contacted`); `say` appends them to the ledger error. Stop the site on `blocked`.
- WhatsApp chats addressed by LID JIDs (no phone number) don't map to a phone; the watcher reports the digits it has.
- Reply timing ("activity blocks", 2–3 h of 3–4-min replies, then a pause) is a skill rule, not enforced in code.
- Price/no-sold detection is a multi-language regex; extend with `nudge.price_extra` / `nudge.no_extra`.
