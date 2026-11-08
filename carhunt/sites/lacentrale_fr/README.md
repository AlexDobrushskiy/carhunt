# lacentrale_fr — La Centrale (lacentrale.fr)

| | |
|---|---|
| wall | DataDome |
| route | plain-chrome (headed, not automated), home page first, jar cookie |
| pace | ≥12 s (unverified); one blocked hit → next rung of the escalation ladder |
| phone | unknown |
| messaging | message-seller form on the ad page (sender lives in contact) |
| readers | query builder only — `search`/`ad`/`is_live` raise `Unsupported` |

## Query
`/listing?makesModelsCommercialNames=VOLKSWAGEN:ID.4[,…]&energies=elec&yearMin=&mileageMax=&priceMax=&customerFamilyCodes=PRO&sortBy=priceAsc&page=N`
— codes in `codes.yaml`. Models missing from the table and `seller=private` → `Unsupported`. Ads: `/auto-occasion-annonce-<id>.html`.

## Rules (why)
- Automated browsers (Playwright lane, identity MCP, Playwright-launched headed Chrome) get the slider; a slide solved
  there → "Access is temporarily restricted". `--headless` fails too.
- A non-automated plain-chrome passes with the jar's cookie; without it the "Slide right" slider, solvable in that
  same browser. Open the home page first, then the listing.
- A stale jar cookie (home page captcha'd with it): solve once, close the browser cleanly so the new cookie
  reaches the jar.
- Repeated blocked hits flag the home IP: after ONE blocked hit move up the ladder.
- Dealer listings only: the private-seller filter returns 0.

## Gaps
- No search/ad reader: the list page state is `window.__PRELOADED_STATE_LISTING__.search` (`total`, `pageSize` 23,
  `hits`); the hit and ad-page shapes are not mapped.
- No liveness reader. Sort orders other than `priceAsc`, `priceMin`, `yearMax`: unverified.
