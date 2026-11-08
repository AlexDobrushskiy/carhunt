"""PR codes (VW group option codes from the boot-floor sticker) -> cardb options.

Table: carhunt/vet/data/prcodes_<brand>.csv with columns code,family,option_key,meaning,confidence.
A meaning starting with "none:" means the code states the option is absent (value "no").
Unknown codes: decode at oemwolf or a dealer printout; see knowledge/pr-codes-vag.md.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources


@dataclass
class Decoded:
    code: str
    option_key: str | None
    value: str | None  # yes | no | None (informational code)
    meaning: str
    confidence: str


@lru_cache(maxsize=None)
def table(brand: str = "vag") -> dict[str, list[dict]]:
    """code -> rows. A code may imply several options (one row each, e.g. a seat package)."""
    path = resources.files("carhunt.vet").joinpath(f"data/prcodes_{brand}.csv")
    if not path.is_file():
        raise FileNotFoundError(f"no PR-code table for brand {brand!r}")
    out: dict[str, list[dict]] = {}
    for r in csv.DictReader(path.read_text(encoding="utf-8").splitlines()):
        if r.get("code"):
            out.setdefault(r["code"].strip().upper(), []).append(r)
    return out


def split_codes(text: str) -> list[str]:
    """Pull 3-char codes out of free text ('3FU, 4E7 / 9M3')."""
    return [c.upper() for c in re.findall(r"\b[0-9A-Z]{3}\b", text.upper())]


def decode(codes: list[str], brand: str = "vag") -> tuple[list[Decoded], list[str]]:
    """Return (decoded, unknown). Duplicates are dropped, input order kept."""
    t = table(brand)
    out, unknown, seen = [], [], set()
    for raw in codes:
        for code in split_codes(raw):
            if code in seen:
                continue
            seen.add(code)
            rows = t.get(code)
            if not rows:
                unknown.append(code)
                continue
            for row in rows:
                key = (row.get("option_key") or "").strip() or None
                meaning = (row.get("meaning") or "").strip()
                value = None
                if key:
                    value = "no" if meaning.lower().startswith("none:") else "yes"
                out.append(Decoded(code, key, value, meaning, (row.get("confidence") or "").strip()))
    return out, unknown


def options(decoded: list[Decoded]) -> dict[str, tuple[str, str]]:
    """option_key -> (value, PR code). A 'yes' wins over a 'no' from a sibling code."""
    res: dict[str, tuple[str, str]] = {}
    for d in decoded:
        if not d.option_key or not d.value:
            continue
        cur = res.get(d.option_key)
        if cur is None or (cur[0] == "no" and d.value == "yes"):
            res[d.option_key] = (d.value, d.code)
    return res


def cardb_args(decoded: list[Decoded]) -> list[str]:
    """Arguments for `cardb opt CAR …` (source vin_pr_code, ref = PR code)."""
    return [f"{k}={v}:vin_pr_code:{code}" for k, (v, code) in sorted(options(decoded).items())]
