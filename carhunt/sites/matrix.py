"""Site matrix for docs/sites.md, rendered from every site.yaml (the single source).

    python -m carhunt.sites.matrix [--check docs/sites.md]   # --check: exit 1 when the doc's matrix is stale
"""
from __future__ import annotations

import sys
from pathlib import Path

from carhunt.sites import base

BEGIN, END = "<!-- site-matrix:begin -->", "<!-- site-matrix:end -->"


def _cell(v) -> str:
    if v in (None, "", [], {}):
        return "—"
    if isinstance(v, list):
        v = ", ".join(map(str, v))
    return " ".join(str(v).split()).replace("|", "\\|")


def render() -> str:
    rows = ["| site | countries | wall | read route | country IP | account needed for | phone | messaging | measured |",
            "|---|---|---|---|---|---|---|---|---|"]
    for p in sorted(base.ROOT.glob("*/site.yaml")):
        if p.parent.name == "fake":
            continue
        m = base.load_meta(p.parent.name)
        acc = (m.get("account") or {}).get("needed_for") or []
        rows.append("| " + " | ".join(_cell(x) for x in (
            m["site"], m.get("countries"), m.get("wall"), m.get("route"), m.get("country_ip"), acc or "none",
            m.get("phone"), m.get("messaging"), m.get("measured"))) + " |")
    return "\n".join(rows)


def splice(doc: str) -> str:
    a, b = doc.index(BEGIN) + len(BEGIN), doc.index(END)
    return doc[:a] + "\n" + render() + "\n" + doc[b:]


def main(argv: list[str]) -> int:
    if argv[:1] == ["--check"]:
        doc = Path(argv[1]).read_text(encoding="utf-8")
        return 0 if splice(doc) == doc else 1
    if argv[:1] == ["--write"]:
        f = Path(argv[1])
        f.write_text(splice(f.read_text(encoding="utf-8")), encoding="utf-8")
        return 0
    print(render())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
