# web

Phone-first UI over cardb (Astro 7 SSR + React islands + Tailwind 4, Node 22). Owner: web.
Full doc: [docs/web.md](../docs/web.md).

```sh
npm ci
npm run dev                         # http://127.0.0.1:4321, talks to CARDB_URL (default http://127.0.0.1:8484)
npm run check && npm test           # types + unit tests (offline)
npm run e2e                         # Playwright vs a throwaway local cardb (needs Go or CARDB_BIN)
npm run gen:api                     # regenerate src/lib/cardb-schema.ts from ../cardb/api/openapi.yaml
```

Env: `CARDB_URL`, `CARDB_WEB_TOKENS` (`name:token,…`) or `CARDB_WEB_TOKENS_FILE`, optional `CARDB_WEB_USER_HEADER`.
