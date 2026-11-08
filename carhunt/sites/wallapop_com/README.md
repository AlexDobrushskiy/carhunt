# wallapop_com — Wallapop (ES)

| | |
|---|---|
| wall | none: the web app's public JSON API (`api.wallapop.com/api/v3`, CloudFront) |
| route | plain HTTP; search `search`, ad = item page (hash id) + `items/<hash>` + `users/<id>` |
| pace | ≥5 s between loads, ≤60/run, reads after 12:00 (or via a proxy) |
| phone | private: none (chat only); professionals: `extra_info.phone_number` in the user API, no reveal |
| messaging | logged-in site chat `es.wallapop.com/app/chat?itemId=<hash id>`, ≤300 chars/message |

## Query
`api/v3/search?category_id=100&keywords=<text>&latitude&longitude&order_by=newest&source=search_box&seller_type=private|professional&min_year&max_km&min_sale_price&max_sale_price`,
then `search?next_page=<token>` (the token carries the query). 40 rows/page. Codes in `codes.yaml` (category, geo
origin, seller, sort, engine labels, keywords per model). No fuel or max-year filter: filter on the cards.

## Rules (why)
- Two ids: URL legacy id (`…-1234567890`) = `site_ref`/liveness/cursor; the API wants the hash id. `ad()` takes it
  from a search row seen by the same instance, else one item-page load (3 loads per ad cold, 2 warm).
- `engine=electric_hybrid` on the item API means battery-electric (site quirk) → `fuel: electric`; the raw code
  stays in `extra.engine`.
- hp comes as `"299.0"`: a decimal, not thousands.
- Bumped rows (`bump.type` city/country) are older than the page around them → `sponsored`, never a cursor.
- A sold/reserved flag in API JSON is informational (`status`); only `is_live` removes an ad — an ad-hoc `"sold"`
  string match marks live cars removed.
- Liveness: page 404 = gone; sold flag in the page JSON = gone; 200 + legacy id = live.
- Chat silently cuts messages at 300 chars → senders split (contact module).
- Messaging-site read budget: ≤60 loads/run and only after 12:00 on the home IP (rule for messaging sites).

## Gaps
- Item `flags` (sold/reserved) are read defensively; they are verified only in the page JSON.
- The item API's creation date is not mapped; cards carry `created_at`.
- No login/sender here (login + chat belong to the browsers + contact modules).
