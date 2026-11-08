# carhunt/discover

`carhunt sweep`: enabled sites → search → cursor → scope → detail read → normalize → cardb. Doc: [docs/discover.md](../../docs/discover.md).

| file | what |
|---|---|
| `runner.py` | plan (read_after, windows), serial sweep, per-site budget, stop at first block, run report |
| `cursor.py` | `newest_id` / `first_seen` / `full` strategies; `$CARHUNT_HOME/discover/cursors.json` |
| `normalize.py` | RawAd/Card → `Listing` (cardb upsert shape): VAT, cash price, flags, power/drive/fuel, phones, regions, options |
| `scope.py` | config `search` → keep / drop with reason |
| `quality.py` | the thin-ad rule + ask list |
| `distance.py` | geocode (Nominatim, cached) + road km / estimate |
| `ingest.py` | cardb writes: upsert without photos → resolve by URL → photos |
| `heuristics/` | model plug-ins (YAML); `vag_meb.yaml` example |
| `data/` | VAT, regions, phone codes, keywords, option cues |
| `cli.py`, `doctor.py` | `carhunt sweep`, doctor checks |
| `_env.py` | discover's view of `carhunt.core` (config dict, paths, clock, cardb client) |
