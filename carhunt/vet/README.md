# carhunt/vet

VIN / registry / PR-code tools and the per-car evidence pack. Docs: [docs/vetbuy.md](../../docs/vetbuy.md); playbooks: [knowledge/](../../knowledge/README.md); skill: `skills/carhunt-vet`.

| file | what |
|---|---|
| `vin.py` | format, ISO 3779 check digit, WMI/country/region, model year, market flags, optional vPIC |
| `rdw.py` | NL RDW open data by plate → `RdwReport` |
| `prcodes.py` | PR codes → cardb options (`data/prcodes_<brand>.csv`) |
| `evidence_pack.py` | evidence-pack state, visit-ready gate, `ask` events |
| `md2html.py` | markdown report → phone-friendly HTML |
| `cli.py` / `doctor.py` | `carhunt vin …`, `carhunt evidence`; doctor checks |
