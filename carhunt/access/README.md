# carhunt/access

Python side of site access (owner: browsers module): sessions (`session.tab`), plain-chrome, identity pool, trust-cookie jar, reaper, pace ledger + day caps, proxies (fail-closed) + geo browser, accounts (creds, email codes, SMS), captcha solver, site-table generator, doctor checks, CLI groups `browser pace proxy sms email-code creds captcha`.

Docs: [docs/browsers.md](../../docs/browsers.md) · agent rules: [skills/carhunt-browsers](../../skills/carhunt-browsers/SKILL.md) · per-site wall evidence: [docs/browsers/site-walls.md](../../docs/browsers/site-walls.md).

Tests: `pytest carhunt/access` (offline; real Chrome only under `-m chrome`). Always run with a temp `CARHUNT_HOME`.
