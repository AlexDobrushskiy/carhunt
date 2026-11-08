# carhunt/contact

Seller contact: one guarded send path (`carhunt say`), channel adapters, one ledger, one watcher, Gmail routing. Full doc: [docs/contact.md](../../docs/contact.md).

| file | what |
|---|---|
| `say.py` | `carhunt say`: flock → guard → send → verify → ledger → cardb |
| `guard.py` | every send rule (pause, caller, target, text, quiet hours, limits, opener/nudge/reply, seller hours, duplicate) — pure |
| `ledger.py` | append-only JSONL of all send attempts; `reconcile` into cardb |
| `settings.py` | defaults merged with `config.yaml` `contact:` |
| `channels/` | `base.py` contract, `whatsapp.py` (wacli), `email.py` (Gmail API), `sites/<site>.py` marketplace chats |
| `watch.py` | `carhunt watch`: inbound → cardb + agent inbox + stdout |
| `mailroute.py`, `gmail.py` | `carhunt mailroute`: car mail out of the inbox; filter XML; launchd template |
| `asks.py` | vet asks (`ask` events) → `ask_answered` |
| `deps.py` | contact's view of `carhunt.core` (config dict, clock, lock, paths, secrets, cardb client) |
| `cli.py`, `doctor.py` | CLI groups `say watch mailroute ledger asks`; doctor checks |

Tests: `CARHUNT_HOME=$(mktemp -d) python -m pytest carhunt/contact -q` (offline: fake wacli, cardb stub, fake Gmail, local fake pages).
