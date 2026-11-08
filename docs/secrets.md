# Secrets

Tokens, passwords and API keys live in a secrets backend, referenced by name. Config holds only `secret:NAME`.

## Lookup order
1. env `CARHUNT_SECRET_<NAME>` (upper-case, non-alphanumerics → `_`): CI, one-off runs, `carhunt secret exec`.
2. `secrets.backend` from config:

| backend | where | notes |
|---|---|---|
| `keychain` (default on macOS) | login keychain, generic password, service `carhunt`, account `NAME` | value goes to `security` on stdin as hex, never in argv. Non-ASCII/multi-line stored as `b64:…`. |
| `op` | 1Password vault `carhunt` (`secrets.op_vault`), item title `NAME`, field `password` | needs `op` signed in |
| `file` | `$CARHUNT_HOME/secrets/NAME`, dir 0700, files 0600 | for Linux / headless |

## Commands
| command | what |
|---|---|
| `carhunt secret set NAME` | no-echo prompt (asked twice); or `… < file` / a pipe |
| `carhunt secret ls` | names + source (`env`/backend), no values |
| `carhunt secret check NAME…` | `ok (source)` / `missing`; exit 1 if any missing |
| `carhunt secret rm NAME` | delete from the backend |
| `carhunt secret exec NAME[=VAR]… -- cmd args` | run `cmd` with the values in its env (`VAR` default: NAME upper-cased) |

There is no `secret get`. Python code calls `secrets.get(name)` and hands the value straight to its use (header, form field, child env).

## Names used by modules
| name | used by |
|---|---|
| `cardb_token` | cardb client (written by `cardb init`) |
| `telegram_bot_token`, `telegram_chat_id` | notify |
| `proxy_credentials`, `sms_api_key` | browsers / access |
| `gmail_oauth_client`, `gmail_token` | contact |
| `site_<domain>_user`, `site_<domain>_pass` | access.creds |

## Rules (why)
- **Never print a secret or a credential file, not even masked.** EV run 2026-11-06: a `grep`/`head` over a creds folder with a masking regex missed `email // password` and ~12 passwords landed in an agent transcript that is still on disk.
- Never put a secret in a ping or a chat message: a notifier hub stored a site password sent as a Telegram message in plain text (EV run). `notify.send` refuses token/key/`password:`-shaped text.
- Secrets reach other programs through env (`secret exec`) or stdin, never argv: argv is visible to every process (`ps`).
- Tests use the `file` backend or a throwaway Keychain service (`carhunt-test-<random>`, deleted after).
