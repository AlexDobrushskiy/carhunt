"""VIN decode: format, ISO 3779 check digit, WMI/region, model year, market flags.

Offline by default. `vpic()` optionally asks NHTSA vPIC (useful for North-American cars only).
"""
from __future__ import annotations

import csv
import json
import re
import urllib.request
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Callable

ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ1234567890"  # ISO 3780 order for country ranges
_TRANSLIT = dict(zip("ABCDEFGHJKLMNPRSTUVWXYZ",
                     [1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4, 5, 7, 9, 2, 3, 4, 5, 6, 7, 8, 9]))
_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
# Position 10 codes; the cycle repeats every 30 years.
_MY_CODES = "ABCDEFGHJKLMNPRSTVWXY123456789"

REGIONS = [("ABCDEFGH", "Africa"), ("JKLMNPR", "Asia"), ("STUVWXYZ", "Europe"),
           ("12345", "North America"), ("67", "Oceania"), ("890", "South America")]

# (first char, second-char range start, end, country). Ranges follow ALPHABET order.
COUNTRIES = [
    ("J", "A", "0", "Japan"), ("K", "L", "R", "South Korea"), ("L", "A", "0", "China"),
    ("M", "A", "E", "India"), ("N", "L", "R", "Turkey"),
    ("S", "A", "M", "United Kingdom"), ("S", "N", "T", "Germany (former GDR codes)"),
    ("S", "U", "Z", "Poland"),
    ("T", "A", "H", "Switzerland"), ("T", "J", "P", "Czechia"), ("T", "R", "V", "Hungary"),
    ("T", "W", "1", "Portugal"),
    ("U", "H", "M", "Denmark"), ("U", "N", "T", "Ireland"), ("U", "U", "Z", "Romania"),
    ("U", "5", "7", "Slovakia"),
    ("V", "A", "E", "Austria"), ("V", "F", "R", "France"), ("V", "S", "W", "Spain"),
    ("V", "X", "2", "France / Serbia (shared)"), ("V", "3", "5", "Croatia"),
    ("W", "A", "0", "Germany"),
    ("X", "L", "R", "Netherlands"), ("X", "S", "W", "Russia"),
    ("Y", "A", "E", "Belgium"), ("Y", "F", "K", "Finland"), ("Y", "S", "W", "Sweden"),
    ("Z", "A", "R", "Italy"),
    ("1", "A", "0", "United States"), ("4", "A", "0", "United States"),
    ("5", "A", "0", "United States"), ("2", "A", "0", "Canada"), ("3", "A", "W", "Mexico"),
]

VAG_WMIS = {"WVW", "WVG", "WV1", "WV2", "WAU", "WUA", "TMB", "VSS"}


@dataclass
class Flag:
    code: str
    severity: str  # info | warn | red
    text: str


@dataclass
class VinInfo:
    vin: str
    valid_format: bool
    errors: list[str] = field(default_factory=list)
    wmi: str = ""
    manufacturer: str | None = None
    wmi_confidence: str | None = None
    region: str | None = None
    country: str | None = None
    vds: str = ""
    vis: str = ""
    model_year: int | None = None
    model_year_candidates: list[int] = field(default_factory=list)
    plant_code: str = ""
    serial: str = ""
    check_digit: dict = field(default_factory=dict)
    flags: list[Flag] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def red(self) -> bool:
        return any(f.severity == "red" for f in self.flags)


def normalize(vin: str) -> str:
    return re.sub(r"[\s\-.]", "", vin or "").upper()


def check_digit(vin: str) -> str:
    """Expected ISO 3779 / NA check digit ('0'-'9' or 'X') for a 17-char VIN."""
    v = normalize(vin)
    if len(v) != 17:
        raise ValueError("VIN must have 17 characters")
    total = 0
    for i, ch in enumerate(v):
        if ch.isdigit():
            val = int(ch)
        elif ch in _TRANSLIT:
            val = _TRANSLIT[ch]
        else:
            raise ValueError(f"invalid VIN character {ch!r} at position {i + 1}")
        total += val * _WEIGHTS[i]
    r = total % 11
    return "X" if r == 10 else str(r)


def with_check_digit(vin: str) -> str:
    """Return `vin` with position 9 set to its correct check digit (for building test VINs)."""
    v = normalize(vin)
    return v[:8] + check_digit(v[:8] + "0" + v[9:]) + v[9:]


@lru_cache(maxsize=1)
def wmi_table() -> dict[str, dict]:
    text = resources.files("carhunt.vet").joinpath("data/wmi.csv").read_text(encoding="utf-8")
    return {row["wmi"]: row for row in csv.DictReader(text.splitlines())}


def region_of(vin: str) -> str | None:
    for chars, name in REGIONS:
        if vin[:1] in chars:
            return name
    return None


def country_of(vin: str) -> str | None:
    if len(vin) < 2:
        return None
    first, second = vin[0], vin[1]
    if second not in ALPHABET:
        return None
    idx = ALPHABET.index(second)
    for f, start, end, name in COUNTRIES:
        if f == first and ALPHABET.index(start) <= idx <= ALPHABET.index(end):
            return name
    return None


def model_year_candidates(code: str) -> list[int]:
    if code not in _MY_CODES:
        return []
    base = 1980 + _MY_CODES.index(code)
    return [base, base + 30]


def _pick_year(vin: str, region: str | None, ref_year: int) -> int | None:
    cands = model_year_candidates(vin[9])
    if not cands:
        return None
    if region == "North America" and len(vin) == 17:
        # NA rule: position 7 numeric -> 1980-2009 cycle, letter -> 2010-2039.
        return cands[0] if vin[6].isdigit() else cands[1]
    plausible = [y for y in cands if y <= ref_year + 1]
    return max(plausible) if plausible else min(cands)


def _reg_year(first_reg: str | None) -> int | None:
    m = re.match(r"^(\d{4})", first_reg or "")
    return int(m.group(1)) if m else None


def decode(vin: str, *, first_reg: str | None = None, ref_year: int | None = None) -> VinInfo:
    """Decode a VIN. `first_reg` (YYYY[-MM]) enables the model-year consistency flag."""
    import datetime as _dt

    v = normalize(vin)
    info = VinInfo(vin=v, valid_format=bool(_VIN_RE.match(v)))
    if len(v) != 17:
        info.errors.append(f"length {len(v)}, expected 17")
    bad = sorted(set(re.sub(r"[A-HJ-NPR-Z0-9]", "", v)))
    if bad:
        info.errors.append("invalid characters: " + "".join(bad) + " (I, O, Q never appear in a VIN)")
    if not info.valid_format:
        info.flags.append(Flag("invalid_format", "red",
                               "Not a valid 17-character VIN: ask for a clear photo of the plate/papers."))
        return info

    ref = ref_year or _dt.date.today().year
    info.wmi, info.vds, info.vis = v[:3], v[3:9], v[9:]
    info.plant_code, info.serial = v[10], v[11:]
    info.region, info.country = region_of(v), country_of(v)
    row = wmi_table().get(info.wmi)
    if row:
        info.manufacturer, info.wmi_confidence = row["manufacturer"], row["confidence"]
    info.model_year_candidates = model_year_candidates(v[9])
    info.model_year = _pick_year(v, info.region, ref)

    expected = check_digit(v)
    mandatory = info.region == "North America" or v[0] == "L"
    info.check_digit = {"expected": expected, "actual": v[8], "valid": expected == v[8],
                        "mandatory": mandatory}
    _flags(info, row, first_reg)
    return info


def _flags(info: VinInfo, row: dict | None, first_reg: str | None) -> None:
    v, add = info.vin, info.flags.append
    market = (row or {}).get("market", "")
    if market == "china_jv":
        add(Flag("china_market", "red",
                 "China-market JV car: likely GB/T charging, no EU warranty, weak resale. "
                 "Treat as a different product."))
    elif v[0] == "L":
        add(Flag("china_built", "info",
                 "Built in China. Fine if it is an EU-export model; confirm with a photo of the "
                 "charging inlet (CCS2, not GB/T)."))
    if info.region == "North America":
        add(Flag("north_america", "warn",
                 "North-American VIN: run the free US salvage screen (EpicVIN preview / stat.vin, never pay), "
                 "check inlet (CCS1/NACS) and EU homologation."))
    cd = info.check_digit
    if not cd["valid"]:
        if cd["mandatory"]:
            add(Flag("check_digit_invalid", "red",
                     f"Check digit is {cd['actual']}, expected {cd['expected']}: typo or altered VIN."))
        else:
            add(Flag("check_digit_unused", "info",
                     "Check digit not used by most EU makers: no signal either way."))
    if info.wmi in VAG_WMIS and v[3:6] == "ZZZ":
        add(Flag("vag_europe", "info", "VW-group 'ZZZ' filler: European-market build."))
    if row is None:
        add(Flag("unknown_wmi", "info", f"WMI {info.wmi} not in the bundled table; look it up."))
    ry = _reg_year(first_reg)
    if ry and info.model_year and not (ry - 2 <= info.model_year <= ry + 1):
        add(Flag("model_year_mismatch", "warn",
                 f"VIN model year {info.model_year} vs first registration {ry}: long storage, "
                 "a re-registered import, or a wrong VIN. Ask."))


def vpic(vin: str, *, fetch: Callable[[str], bytes] | None = None, timeout: float = 15) -> dict:
    """NHTSA vPIC DecodeVinValues (free, no key). Returns the non-empty fields."""
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{normalize(vin)}?format=json"
    raw = fetch(url) if fetch else urllib.request.urlopen(url, timeout=timeout).read()
    results = json.loads(raw).get("Results") or [{}]
    return {k: v for k, v in results[0].items() if v not in ("", None, "Not Applicable", "0")}
