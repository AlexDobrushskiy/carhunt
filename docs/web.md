# web — phone-first UI over cardb

Astro 5 SSR + React islands + Tailwind 4, Node 22. A pure cardb API consumer: no own storage. Code: `web/`.

## Commands (in `web/`)

| command | what |
|---|---|
| `npm ci` | install (Node 22; `npm run check` crashes on Node 20) |
| `npm run dev` | dev server on `127.0.0.1:4321` |
| `npm run build && npm start` | production server (`HOST`, `PORT`) |
| `npm run check` | `astro check` + `tsc` |
| `npm test` | vitest unit tests, offline (filters, queue, proxy allowlist, identity, profile, powertrain, format, lightbox; schema sync when `cardb/` is checked out) |
| `npm run e2e` | Playwright, iPhone 13 viewport, against a throwaway local stack (below) |
| `npm run gen:api` | regenerate `src/lib/cardb-schema.ts` from `../cardb/api/openapi.yaml`; commit it with the spec change |

## Config (env only)

| var | default | what |
|---|---|---|
| `CARDB_URL` | `http://127.0.0.1:8484` (image: `http://cardb:8484`) | cardb base, without `/api/v1` |
| `CARDB_WEB_TOKENS` | — | `name:token` pairs (comma/space/newline separated). Name = cardb token name = user. First pair = default viewer unless one is named like `owner.name` |
| `CARDB_WEB_TOKENS_FILE` | — | same, from a file (Docker secret); used when `CARDB_WEB_TOKENS` is empty |
| `CARDB_WEB_USER_HEADER` | — | trusted header set by an auth proxy (e.g. `Remote-User`). Pins the identity, hides the picker; an unknown name → 403 |
| `HOST`, `PORT` | `127.0.0.1`, `4321` | listen address (image: `0.0.0.0`) |

No config.yaml section: labels, tiers, option keys, home city and time zone come from `GET /api/v1/profile` (cached 60 s, last good copy kept on error).

## Routes

| path | what |
|---|---|
| `/` | car list. `view=` `active` (default) `review` `needs` `to_contact` `talking` `visit` `liked` `dups` `closed` `all`. Filters: `q family* market=home\|abroad fuel* year_min year_max price_min price_max hp_min hp_max drive* km_max distance_km_max country* seller_type* status* verdict* opt_<key> good_deal=1 sort order` |
| `/queue` | "To rate": `GET /queue` for the viewer. `all=1` adds non-default tiers, `spec=confirmed\|unknown` (chips named after `must_have`), `limit` |
| `/cars/[id]` | car page; aliases/merged ids redirect to the live id |
| `/photos/[id]?size=thumb\|medium\|full` | photo proxy, immutable cache |
| `/ui/*` | browser writes → allowlisted `/api/v1/*` with the viewer's token |
| `/identity` (POST) | "Viewing as" picker: sets the `carhunt_user` cookie (a name, not a token) |
| `/health` | web liveness |

## Rules (with why)

- **The browser never sees a token.** Tokens live in env; the browser holds only a user name cookie; `/ui/*` adds the token server-side. A `?token=` on photo URLs leaked into history and logs in the EV run.
- **`/ui/*` is an allowlist** (verdict, notes, status, needs flag, good deal, merge, reject duplicate); everything else → 405. Viewers get verdict only (cardb enforces it too → 403). A UI bug must not become an arbitrary API write.
- **Author is forced to the viewer** (`author` + `X-Author` = token name; `user` too on verdicts). A client cannot write as someone else, and every write is attributable.
- **Cross-site writes are refused** (`Origin`/`Sec-Fetch-Site` vs `Host`/`X-Forwarded-Host`). The identity cookie would otherwise ride along on a forged POST.
- **The picker is not authentication.** Anyone who reaches the web can pick any configured identity. Keep it on localhost / Tailscale, or set `CARDB_WEB_USER_HEADER` behind an auth proxy.
- **Per-user verdicts:** reads pass `?user=<viewer>` (only for names in `/profile` users; cardb 422s on others), so lists, the queue and "To review" are the viewer's own. Other users' verdicts show beside yours.
- **Edits send the car `version`** (status, needs flag): a stale page gets "changed by someone else, reload" (412) instead of silently undoing an agent's write.
- **Unknown ≠ no.** A missing option row is `?`, never ✗; filters offer `✓ or ?`. A wrong ✗ hides a good car.
- **Gzip HTML in middleware.** A 230-car list went 760 KB → 42 KB on a phone. No JS framework on the list; islands only on the car page.
- **Times in `owner.tz`**, whatever zone the server runs in.
- **Price gap sign:** cardb's `price_gap_pct` is positive when cheaper; the chip shows the price relative to fair (−12 % = 12 % under).
- **e2e never touches a non-local URL** and never real data: global setup starts its own cardb on a temp dir with synthetic cars (`example.invalid`, `SYN…` VIN, `+351 555…`), and `fixtures.ts` refuses a non-loopback base URL. The EV run's first e2e wrote test events into a real car.
- **e2e helpers must not depend on DOM order**; select by `data-testid` / roles.

## e2e

`npm run e2e` → `e2e/global-setup.ts` → `e2e/stack.ts`:
1. cardb binary: `CARDB_BIN`, else `go build ../cardb`, else `cardb` on PATH.
2. Temp `CARHUNT_HOME` with a synthetic profile (owner `Sam`, viewer `Kim`, tiers by model, `must_have: [electric_seats]`), `cardb serve` on a free loopback port with three random tokens; the child gets a minimal env (no inherited `CARDB_*`/`CARHUNT_*`).
3. Seeds 4 cars over REST (BEV with photos/options/facts/needs flag, diesel, two queue cars).
4. `npm run build` (skip: `E2E_SKIP_BUILD=1`), starts the web on another free port; teardown kills both and removes the temp dir and `dist/` (its server key trips gitleaks).

Specs (`e2e/web.spec.ts`): list → fuel filter → car page (powertrain block, distance label) → verdict + note, persisted; diesel page; viewer identity (read-only controls, own verdict, proxy 403, owner's verdict untouched); `Needs <owner>` tab; queue rate → collapse → undo, tier toggle; lightbox; no token in HTML, cross-site and off-list writes refused. `E2E_VERBOSE=1` shows cardb's request log.

## Docker / compose

`web/Dockerfile`: pinned `node:22.23.4-alpine`, multi-stage, non-root, healthcheck on `/health`. Service block for `deploy/compose.yaml` (owned by db):

```yaml
  web:
    build: ../web
    environment:
      CARDB_URL: http://cardb:8484
      CARDB_WEB_TOKENS_FILE: /run/secrets/cardb_web_tokens
    secrets: [cardb_web_tokens]
    ports: ["127.0.0.1:4321:4321"]
    depends_on: {cardb: {condition: service_healthy}}
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 256m
secrets:
  cardb_web_tokens: {file: "${CARHUNT_HOME:-~/.carhunt}/cardb/web-tokens"}   # name:token per line, 0600
```

## Gaps

- No i18n: UI text is English; chat shows in the original language.
- Currency display is EUR (cardb stores `_eur` prices).
- The list card can't show "sold" (no sold count in `CarSummary`).
- Identity picker = trust the network; real per-person login needs an auth proxy + `CARDB_WEB_USER_HEADER`.
