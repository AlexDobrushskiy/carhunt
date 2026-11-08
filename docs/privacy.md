# Privacy

carhunt handles phone numbers, seller chats, VINs, site accounts and payment details. None of it may enter the repo.

| lives in | what |
|---|---|
| repo | code, templates with `{placeholders}`, synthetic fixtures, docs |
| `$CARHUNT_HOME` (default `~/.carhunt`) | `config.yaml`, cardb data + photos, ledgers, rendered agent briefs, `state.json`, logs, browser profiles, cursors |
| secrets backend | tokens, passwords, API keys (Keychain / 1Password / `$CARHUNT_HOME/secrets/`, 0600) |

## Rules
- Never print a secret or a credential file, not even masked. Use `carhunt secret exec` to pass one to a command.
- Fixtures are synthetic: VINs start `SYN`, phones `+<cc> 555 …`, emails `@example.com`, URLs `https://example.invalid/…`.
- No screenshots, logs or DB dumps in commits.

## The check
`scripts/install-hooks` wires `scripts/privacy-check` as pre-commit and commit-msg hooks.
- gitleaks (`brew install gitleaks`) for secret shapes.
- **Denylist**: your own words that must never appear (real names, your phone, your city, dealer names…), one per line, case-insensitive. Default path `~/.config/carhunt/privacy-denylist.txt`, override with `CARHUNT_DENYLIST`. Keep it outside the repo. Hits are reported by denylist line number, never by the term.
- Regexes: phone, email, IBAN, VIN, API-key shapes, absolute home paths.
- `scripts/privacy-check --all` scans the working tree; `--history` scans every commit (run before any push).
- A deliberate synthetic value that still trips a regex: add `privacy-check: allow` on that line.
