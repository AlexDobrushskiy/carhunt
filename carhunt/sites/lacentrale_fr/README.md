# lacentrale_fr — La Centrale (lacentrale.fr)

| | |
|---|---|
| wall | DataDome |
| route | plain-chrome (headed, not automated), home page first, jar cookie |
| pace | ≥12 s (not measured); one blocked hit → next rung of the escalation ladder |
| phone | not measured |
| messaging | message-seller form on the ad page (not measured; sender lives in contact) |
| readers | query builder only — `search`/`ad`/`is_live` raise `Unsupported` |

## Query
`/listing?makesModelsCommercialNames=VOLKSWAGEN:ID.4[,…]&energies=elec&yearMin=&mileageMax=&priceMax=&customerFamilyCodes=PRO&sortBy=priceAsc&page=N`
— codes in `codes.yaml`. Models missing from the table and `seller=private` → `Unsupported`. Ads: `/auto-occasion-annonce-<id>.html`.

## Rules (why)
- Automated browsers (Playwright lane, identity MCP, Playwright-launched headed Chrome) get the slider; a slide solved
  there → "Access is temporarily restricted" (10-26). `--headless` fails too (10-25).
- A non-automated plain-chrome passes with the jar's cookie; without it the "Slide right" slider, solvable in that
  same browser (2/2, 10-26). Open the home page first, then the listing.
- A stale jar cookie (home page captcha'd with it, 10-26): solve once, close the browser cleanly so the new cookie
  reaches the jar.
- ~10 blocked test hits in an hour flagged the home IP (10-25): after ONE blocked hit move up the ladder.
- Dealer listings only: the private-seller filter returned 0.

## Gaps
- No search/ad reader: the list page state (`window.__PRELOADED_STATE_LISTING__.search`: `total`, `pageSize` 23,
  `hits`) was only ever captured with 0 hits, and no ad page was captured. Capture one non-empty list page and one ad
  page (synthetic fixtures from them) before writing the parsers.
- No liveness reader (3 listings in the EV run). Sort orders other than `priceAsc`, `priceMin`, `yearMax`: not measured.
