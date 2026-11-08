# Notify

Pushes to the owner's phone (Telegram, optional) and the way the owner's answers get back to the agent that asked.

## Policy (enforced in code)
| kind | for | quiet hours (`notify.quiet_hours`) |
|---|---|---|
| `digest` | the scheduled summaries (`orchestrate.schedule.digest`, e.g. 09:30 / 20:00) | held until the window ends |
| `ask` | a decision that blocks progress today; `--buttons "A\|B"` or a free answer | held |
| `urgent` | a breach or a dead session the agent could not fix itself (PAUSE first) | sent silent |

Anything else (`fyi`, "sent", "scheduled", heartbeats, research with no ask) is **refused** (exit 10): it goes into the next digest. Per-kind quiet behaviour can be changed: `notify.quiet: {ask: silent}`.
Also refused: buttons on a non-`ask`, empty text, text that looks like a token/key/password.

## Commands
| command | what |
|---|---|
| `carhunt notify send --agent A --kind digest\|ask\|urgent [--buttons "A\|B"] [--ask] TEXT\|-` | prints `sent ref=telegram:<id>` / `held until …` / `dropped`; exit 10 refused, 11 failed |
| `carhunt notify inbox list --agent A [--all] [--json]` | unacked owner lines for agent A |
| `carhunt notify inbox wait --agent A [--timeout S] [--no-poll]` | block until a line arrives (exit 1 on timeout). It drives the Telegram poller itself, so no daemon is needed. |
| `carhunt notify inbox ack --agent A ID…` | mark handled (don't ack lines you hand over to a successor) |
| `carhunt notify poll [--once]` | long-poll loop: route replies, flush held messages |

`--agent` defaults to `$CARHUNT_AGENT` (set by `carhunt agent launch`).

## Reply routing
- A reply (Telegram "reply" on the ping) or a button press goes to the agent that sent that ping: `$CARHUNT_HOME/agents/<agent>/inbox.jsonl`, item `{id: "tg-<update_id>", ts, source: telegram, kind: text|button, text, re, re_text}`.
- A line that replies to nothing goes to `notify.default_agent` (default `overseer`).
- Only `chat_id` is listened to; other chats are ignored. Voice/photo lines arrive as `[voice message: open Telegram to see it]`.
- One poller at a time (flock + Telegram's own rule); state in `$CARHUNT_HOME/notify/` (`offset`, `sent.jsonl`, `held.jsonl`).
- Other writers (contact's watcher) add lines with `inbox(agent).add({...})`; ids must be unique.

## Telegram setup
1. In Telegram, talk to **@BotFather** → `/newbot` → name + username → copy the token.
2. `carhunt secret set telegram_bot_token` (paste; nothing echoes).
3. Send any message to your new bot, then find your chat id:
   `carhunt secret exec telegram_bot_token=T -- sh -c 'curl -s "https://api.telegram.org/bot$T/getUpdates"' | jq '.result[].message.chat.id'`
4. `carhunt secret set telegram_chat_id`.
5. Config: `notify: {backend: telegram, telegram: {bot_token: secret:telegram_bot_token, chat_id: secret:telegram_chat_id}}`.
6. `carhunt doctor` → `notify telegram: ok`; test: `carhunt notify send --agent overseer --kind ask --buttons "Yes|No" "Does this reach you?"`, press a button, `carhunt notify poll --once`, `carhunt notify inbox list --agent overseer`.

Privacy: a bot sees only chats where someone wrote to it. Keep it private: BotFather → `/setjoingroups` → Disable. The token gives full control of the bot: if it leaks, `/revoke` in BotFather and `secret set` the new one.

## Config
Keys and defaults: [`config.example.yaml`](../config.example.yaml) `notify:` (backend, Telegram secret names, `quiet_hours` in `owner.tz`, per-kind `quiet`, `default_agent`). Optional `notify.telegram.api_base` (default `https://api.telegram.org`).

## Rules for agents (why)
- Answering an owner line: one reply, nothing after it.
- A decision that can wait for the next digest waits.
- Never a secret in a ping ([secrets.md](secrets.md#rules-why)); `send` refuses token-shaped text.
