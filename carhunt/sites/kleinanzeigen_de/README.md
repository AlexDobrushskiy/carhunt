# kleinanzeigen_de — Kleinanzeigen (DE)

| | |
|---|---|
| wall | Akamai Bot Manager — not triggered by reads |
| route | plain HTTP, Chrome UA; server-rendered HTML (no JSON blob) |
| pace | ≥6 s between loads |
| phone | `text-only`: no reveal button; numbers the seller typed into the description (German mobiles 015x–017x → +49) |
| messaging | site chat, logged in (inbox `/m-nachrichten.html`); sender lives in contact |

## Query
`/s-autos/<make>/anbieter:privat|gewerblich/preis:<min>:<max>/seite:N/c216+autos.ez_i:<ymin>%2C<ymax>+autos.fuel_s:elektro+autos.km_i:%2C<km>+autos.marke_s:<make>+autos.model_s:<model>`
— the shape of the site's own facet links (attributes sorted). Models without a known `model_s` slug fall back to a
free-text keyword (`/s-autos/<keyword>/k0c216+…`). Codes in `codes.yaml`. 27 rows/page; stops at "von N Ergebnissen".

## Parsing
- Cards: `<article data-adid data-href>` rows + their JSON-LD (title, thumb) + text tags (price, "41.000 km", "EZ 05/2023", "PLZ City", date). List rows carry no seller type: it comes from the `anbieter:` filter.
- Ad: the analytics `dimensions` object (`ad_id`, `ad_price`, `ad_seller_type`, `postal_code`, `ad_attributes` = `ez_i/ezm_i/km_i/power_i(PS)/schaden_s/full_service_history_b/…`), `#viewad-title`, `#viewad-description-text`, details list, seller link, gallery `data-imgsrc` (two sizes per photo → deduped).

## Rules (why)
- `schaden_s:f` = accident-free, `full_service_history_b:t` = full service history; `power_i` is PS (kW = PS × 0.7355).
- Account actions (signup, activation link) hit "IP-Bereich vorübergehend gesperrt" on a home ISP range and 403 on datacenter IPs: do them over mobile data. Reads are not challenged.
- `data-soldlabel="Verkauft"` sits on every ad title: it is not a sold flag.

## Gaps
- Gone: 404/410 assumed; the "Anzeige ist nicht mehr verfügbar" marker is unverified.
- `seite:N` placement verified on make/attribute lists only; pagination of keyword URLs (`k0c216`) is unverified.
- Sponsored rows ("TOP" ads) are not detected. Sorts other than the default (newest) raise `Unsupported`.
- `model_s` slugs known only for the models in `codes.yaml` (seen in the site's links); others use the keyword search.
