# Privacy

carhunt handles phone numbers, seller chats, VINs, site accounts and payment details. None of it may enter the repo.

| lives in | what |
|---|---|
| repo | code, templates with `{placeholders}`, synthetic fixtures, docs |
| `$CARHUNT_HOME` (default `~/.carhunt`, mode 700) | `config.yaml`, cardb data + photos, send ledger, rendered agent briefs, `state.json`, inboxes, logs, browser profiles + cookie jar, cursors, agent `claude/settings.json` |
| secrets backend | tokens, passwords, API keys (Keychain / 1Password / `$CARHUNT_HOME/secrets/`, 0600) — [secrets.md](secrets.md) |

## Rules
- Secrets: never printed, not even masked; passed by env or stdin ([secrets.md](secrets.md#rules-why)). Agents are held to it by the `secret-guard` hook ([orchestrate.md](orchestrate.md#guard-hooks-hookscarhunt_hookpy-stdlib-only)).
- Fixtures are synthetic: VINs start `SYN`, phones `+<cc> 555 …`, emails on `example.*` / `*.invalid` / `*.test`, URLs `https://example.invalid/…`.
- No screenshots, captured pages, logs or DB dumps in commits. A parser test needs a page shape → build it by hand with fake values.
- Tests never touch your real home or Keychain ([testing.md](testing.md#isolation-rules-every-test)).

## The check
`scripts/install-hooks` (run by bootstrap) wires `scripts/privacy-check` as pre-commit and commit-msg hooks.
- gitleaks (`brew install gitleaks`) for secret shapes.
- **Denylist**: your own words that must never appear (real names, your phone, your city, dealer names…), one per line, case-insensitive. Default path `~/.config/carhunt/privacy-denylist.txt`, override with `CARHUNT_DENYLIST`. Keep it outside the repo. Hits are reported by denylist line number, never by the term.
- Regexes: phone, email, IBAN, VIN, API-key shapes, absolute home paths.
- Modes: no args = staged changes · `--all` = working tree · `--history` = every commit and message on all refs (run before any push) · `FILE…`.
- A deliberate synthetic value that still trips a regex: add `privacy-check: allow` on that line.
- Never commit with `--no-verify`; a hit means remove the word, not skip the check.
