# Identity pool, logins, site accounts, verification codes

Reference for the `carhunt-browsers` skill. Hold/release rules stay in SKILL.md.

## Identity pool
| browser | MCP name | profile | notes |
|---|---|---|---|
| master | `ch-identity` | `profiles/identity` | the only one for Google; localStorage logins live here |
| copies | `ch-identity-a…d` (`browsers.identity_pool`) | `profiles/identity-<x>` | APFS clones of the master (`pw-identity seed`), minus Google cookies |

- **Cookie sync** carries logins: a copy's close pushes newer cookies to the master (or a pending store if the master is running); a copy's launch pulls master + pending. So a login made in any copy reaches all. Why one master: Google logs out a session it sees in several profiles (10-21) → Google cookies never sync.
- Leases: one holder per browser. Claude Code PreToolUse/PostToolUse hooks (`pw-identity hook pre|post`; render with `carhunt browser mcp-config --hooks` and merge into settings.json) take/refresh/release the lease; idle > `browsers.idle_release_s` → released and closed. Codex/other CLIs have no hooks → they must `pw-identity acquire` themselves.
- `pw-identity [-b <browser>] status` (holder) · `pool` (all + free + seed age) · `acquire <name> [--any | --pool | -b <browser>]` (scripts: free copy first, master only if none free; prints the profile path) · `[-b <browser>] release [--force]` · `seed <x|--all|--stale H>` · `[-b <browser>] login [url]` (non-automated window for a manual sign-in / one-time solve) · `sync` · `reap` · `[-b <browser>] restart`.
- Stale copy (site API 401, missing session) → `pw-identity seed --all` (olx 401, custojusto, 11-04/05).

## Log in yourself
- Credentials: `carhunt.access.creds.login(site)` → `(user, password)` from secrets `site_<domain>_user` / `site_<domain>_pass`. Use them inside the script that fills the field; never print, echo, log or return them to the transcript.
- **Never `cat`/`grep`/`head` a secrets dir or creds file, not even masked** (11-06: one grep leaked ~12 passwords into a transcript).
- Never snapshot/screenshot a sign-in page with a password typed (captures the field value). Tick "keep me signed in".
- Sign in on an identity profile so it persists for later agents: `with tab("identity", site=…)` (plain launch on a free copy; cookie sync spreads it).
- Blocked as automation on a login page (Cloudflare "Just a moment", Google)? Don't hand the owner a click path: `pw-identity acquire <you> --any`, then `plain-chrome --profile <path> open <url>` and drive it. Akamai/DataDome sites block even a Playwright-launched headed Chrome (10-25).

## Create site accounts
- Agents create the accounts they need, with the owner's main email (`accounts.email`) or a plus-address (`accounts.gmail.plus_address`), and a generated password: `creds.new(<domain>, <email>)` (stores `site_<domain>_user/_pass`, prints neither, refuses to overwrite).
- Real name + photo on the profile helps with private sellers (11-04); many sites allow the photo only in their app → skip, don't ask.
- Forms demanding domestic data you don't have (local mobile, postcode) → stop and report; never invent values (coches.net, 11-05).
- "Continue with Google" only: never type the owner's Google password on a third-party site; use the site's guest form instead (AutoScout24).

## Verification codes and links
- **Email first**, even when the site says "texted" (one arrived by email, 10-31): `from carhunt.access.accounts import wait_code, wait_link`; take `t0 = time.time()` **before** the site sends, then `wait_code(site, since=t0)` / `wait_link(site, since=t0, pattern=…)`. Read-only Gmail API, token from secrets; query = site.yaml `account.mail_from`, else `from:<domain>`.
- A code that goes **only** to the owner's phone → one `ask` notification, batched with any other pending codes (owner, 10-21: agents must not be blocked by anything they can do themselves).
- Some activations fail on IP, not the number: kleinanzeigen refused the activation link on a residential range ("IP-Bereich vorübergehend gesperrt") until the owner opened it on mobile data (11-02).
- Phone verification: try the owner's own number first (subito accepted a foreign EU mobile, 11-02). Rented numbers: see proxies-and-sms.md.

## Gmail OAuth (for email codes)
- Own Google Cloud OAuth client (Desktop), scopes `gmail.readonly` (+ `gmail.modify` only if mail routing needs labels). **Publish it "In production" at creation.** Why: in Testing, refresh tokens die after 7 days; every Gmail-dependent agent died at once (11-06).
- Unverified + restricted scope → consent shows "Google hasn't verified this app" → Advanced → continue; expected for a personal client (≤100 users).
- Re-auth opens the consent URL in the OS default browser (the owner's, signed in: one click). In an agent browser Google adds a "verify it's you" step → phone tap.
