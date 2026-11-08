# carhunt/sites

One plugin per marketplace (`<pkg>/plugin.py` + `site.yaml` + `codes.yaml` + `README.md`) and the liveness checker. Doc: [docs/sites.md](../../docs/sites.md).

| file | what |
|---|---|
| `model.py` | `SearchQuery`, `Card`, `RawAd`, `Seller`, `Liveness` |
| `base.py` | `Site` protocol, `BaseSite`, registry (`get`, `ids`, `for_url`), `Gone`, `Unsupported`, `Blocked` |
| `_net.py` | transport: pace gate → HTTP or browser tab → block/gone classification |
| `extract.py` | page data extractors (`__NEXT_DATA__`, RSC flight, window vars, JSON-LD) + number/date helpers |
| `live.py` | liveness classifier + default `is_live` |
| `liveness.py` | `carhunt liveness` runner (cardb writes, state) · `liveness.plist.tmpl` launchd job |
| `cli.py`, `doctor.py`, `matrix.py` | CLI groups `site`/`liveness`, doctor checks, docs matrix |
| `testing.py` | `FakeNet` for offline tests · `fake/` test site (`CARHUNT_FAKE_SITES=1`) |
| `site.schema.json` | site.yaml schema |

Tests: `pytest carhunt/sites` (offline).
