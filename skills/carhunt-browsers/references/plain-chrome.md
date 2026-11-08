# Agent Chrome, plain-chrome, trust-cookie jar, captcha solver

Reference for the `carhunt-browsers` skill. State lives under `$CARHUNT_HOME/browsers/`.

## Agent Chrome (`agent-chrome`)
- The installed Chrome APFS-cloned to `$CARHUNT_HOME/browsers/agent-chrome/` under its own bundle id, ad-hoc re-signed, rebuilt when Chrome updates (server start + a periodic launchd refresh). Same binary → sites see plain Chrome. `agent-chrome` prints the executable path; `CARHUNT_CHROME` overrides.
- Scripts pass that path as `executable_path`, never `channel="chrome"` (that's the owner's Chrome: macOS confuses the two).
- Any launch on a persistent profile adds `--use-mock-keychain --password-store=basic`. Why: without them a plain launch on the identity profile wipes every login.

## plain-chrome
Agent Chrome started like a person starts it (only `--remote-debugging-port`, headed, off-screen, no focus steal); Playwright/CDP attaches only after the first load committed, then may keep navigating that tab. Why: Akamai/DataDome block Playwright-*launched* Chrome (its launch switches + live CDP during the first load) but pass this one (e.g. mobile.de, lacentrale).

| command | does |
|---|---|
| `plain-chrome fetch [opts] URL…` | open on the first URL, attach, visit the rest in the same tab; one JSON line per URL (`url, final, title, blocked, len`) + `<out>/NN.{txt,html,jpg}` |
| `plain-chrome open [opts] URL` | leave it running; prints `{"cdp","port","target","profile","reused"}`. Drive **only the tab whose targetId == `target`** (other agents may have tabs in the same browser) |
| `plain-chrome close PORT [TARGET]` | close your tab; browser closes cleanly (cookies flushed → jar) when the last tab goes. Without TARGET only if nobody else has a tab |
| `plain-chrome show\|hide PORT [TARGET]` | bring the window on-screen for the owner's one-time solve / move it back |
| `plain-chrome status` | running browser, port, tabs + holders |
| `plain-chrome cookies [--delete DOMAIN NAME]` | list the trust-cookie jar (site, cookie, expiry; never values) / delete one row |

Opts: `--profile DIR` (persistent profile, e.g. an identity copy after `pw-identity acquire`), `--fresh` (throwaway profile, still jar-seeded; only to test whether the IP is flagged), `--warm URL` (load the site home first; some DataDome sites captcha a cold deep link), `--wait S` (settle time, default 10, first load 15), `--headless` (loses the advantage on Akamai/DataDome; only where the site row says ✓), `--out DIR`.

- **Shared persistent profile** (`profiles/plain`): a second caller gets a new tab in the running browser, not a second browser. Why: two browsers = two captchas.
- Off-screen window: macOS clamps it to the top-left behind other windows; Playwright `.click()` may fail → `el.evaluate(e => e.click())` or Enter. A filled form can end up in a visible window → close forms at once.

## Trust-cookie jar (`jar/jar.sqlite`)
- Holds **bot-check cookies only** (`datadome`, `_abck`/`bm_*`, `cf_clearance`, `reese84`, `_px*`), never logins.
- Written from every plain-chrome on clean close and from identity profiles at launch; seeded into every plain-chrome/identity launch. So one solve (agent or owner) carries to all browsers.
- Python: `carhunt.access.jar` `get(domain, name)` lets plain-HTTP helpers reuse a browser-minted DataDome cookie (leboncoin reads).
- Poisoned entry (every browser blocked, `--fresh` passes) → `plain-chrome cookies --delete <domain> <name>`.

## DataDome 403 + "slide right" on the first request
- (a) Playwright launched the browser → plain-chrome passes.
- (b) IP flagged (fresh plain-chrome blocked too) → solve in that browser (ladder rung 6); fails → owner once via `pw-identity login <url>`.
- Lanes carry no jar cookie → they stay blocked: these sites go to plain-chrome / identity.

## Captcha solver (`carhunt captcha`, optional)
Local only: no paid service, never pings anyone. Needs `browsers.captcha.enabled: true`; image grids need Ollama + a small VLM (`captcha.model`, default `qwen3.5:4b`) and OWLv2 (PyTorch).

| command | does |
|---|---|
| `carhunt captcha solve --cdp http://127.0.0.1:PORT --target T` | solve on a plain-chrome tab |
| `carhunt captcha solve --lane --url PART` / `--identity[-x] --url PART` | solve on a tab you opened with MCP tools (attaches via the server's debug port; the MCP session keeps working) |
| `plain-chrome open URL` then `carhunt captcha solve --plain --url PART` | open + solve; tab stays open → `plain-chrome close` |
| `carhunt captcha stats` | attempts / successes per site and kind |

- Prints one JSON line: `solved` / `failed` / `hard-block` (ban, nothing to solve) / `unsupported` (e.g. hCaptcha image tasks) / `budget`.
- Handles: DataDome slider (incl. retry), GeeTest/puzzle sliders (OpenCV), Turnstile / reCAPTCHA / hCaptcha checkbox, reCAPTCHA 3×3/4×4 grids, PerimeterX hold.
- Budget: 2 attempts per run, 6 per site per 6 h. Why: each failed attempt raises the bot score.
- After a solve: `plain-chrome close` so the new cookie reaches the jar.
- Not used: reCAPTCHA audio (Google rejects answers from these browsers).
