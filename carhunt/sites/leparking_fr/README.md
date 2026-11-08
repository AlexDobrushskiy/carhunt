# leparking_fr — leparking.fr (aggregator)

| | |
|---|---|
| wall | Cloudflare |
| route | lane ✓ (11-02) |
| pace | ≥6 s (not measured) |
| phone / messaging | none: contact the seller on the source site |
| readers | query builder + filter JS only — `search`/`ad`/`is_live` raise `Unsupported` |

French aggregator (leboncoin, La Centrale, ParuVendu, AutoScout24.fr, ev-market): use it to find **cross-posts of one
car** (same car, other sites, other price). It misses part of leboncoin, so "absent here" proves nothing.

## Query
`/voiture-occasion/<make>-<model>.html` (slug table in `codes.yaml`; unknown models → `Unsupported`). Country and
private-seller filters have no URL params, only in-page JS (`filter_js(q)`):
`ctrl.set_criteria('id_pays',18,'FRANCE',window); ctrl.set_criteria('id_vendeur',1,'Particuliers',window); ctrl.need_refresh()`.

## Rules (why)
- `/tools/<id>/0/P/P.html` redirects to the source ad: open DataDome sources (leboncoin, La Centrale) in their own
  route (plain HTTP + cookie / plain-chrome), never in the lane — an automated browser there gets the slider.

## Gaps
- No search reader: the result rows were never captured; the slug rule beyond the measured example, pagination and
  other filter ids (dealer, other countries) are unknown.
- No liveness: rows point at source ads; check those.
