"""NL RDW open data by plate (free, no key): import date, odometer verdict, open recalls.

Datasets: m9d7-ebf2 (registered vehicles), t49b-isb7 (recall status per plate).
Not in open data: km values and owner count — the owner can request the free
RDW-Voertuigrapport (DigiD) and forward it; Finnik.nl shows an owner-type timeline.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Callable

BASE = "https://opendata.rdw.nl/resource"
VEHICLES = "m9d7-ebf2"
RECALLS = "t49b-isb7"

# Dataset jqs4-4kvw, paraphrased.
ODOMETER_CODES = {
    "00": ("logical", "every reading higher than the one before"),
    "01": ("no verdict", "odometer rolled over / does not count to 999,999"),
    "02": ("no verdict", "odometer replaced or repaired"),
    "03": ("logical", "every reading higher than the one before"),
    "04": ("ILLOGICAL", "a lower reading after a higher one (since 2014): possible rollback"),
    "05": ("no verdict", "registered abroad before, or re-plated"),
    "06": ("no verdict", "fewer than 2 readings"),
    "07": ("ILLOGICAL (NAP, pre-2014)", "earlier NAP verdict 'illogical'"),
    "NG": ("not registered", ""),
}

Fetch = Callable[[str], bytes]


@dataclass
class RdwReport:
    plate: str
    found: bool
    make: str | None = None
    model: str | None = None
    first_admission: str | None = None        # first registration anywhere
    first_nl_registration: str | None = None
    last_owner_change: str | None = None
    imported: bool | None = None
    odometer_code: str | None = None
    odometer_verdict: str | None = None
    odometer_note: str | None = None
    odometer_last_year: str | None = None
    open_recall: bool | None = None
    recalls: list[dict] = field(default_factory=list)
    apk_expiry: str | None = None
    exported: bool | None = None
    insured: bool | None = None
    catalogue_price: int | None = None
    red_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def fact_value(self) -> str:
        """One-line summary for `cardb fact CAR rdw=…`."""
        if not self.found:
            return f"RDW: plate {self.plate} not found"
        parts = [f"first adm {self.first_admission}", f"NL reg {self.first_nl_registration}",
                 "imported" if self.imported else "NL-new",
                 f"odometer {self.odometer_verdict}",
                 "OPEN RECALL" if self.open_recall else "no open recall",
                 f"APK until {self.apk_expiry or '-'}"]
        return "RDW: " + "; ".join(parts)


def normalize_plate(plate: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())


def _date(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()[:10]
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _yes(s: str | None) -> bool | None:
    if s is None:
        return None
    return s.strip().lower() in ("ja", "j", "yes", "true")


def parse(plate: str, vehicles: list[dict], recalls: list[dict] | None = None) -> RdwReport:
    p = normalize_plate(plate)
    if not vehicles:
        return RdwReport(plate=p, found=False)
    v = vehicles[0]
    r = RdwReport(plate=p, found=True, make=v.get("merk"), model=v.get("handelsbenaming"))
    r.first_admission = _date(v.get("datum_eerste_toelating"))
    r.first_nl_registration = _date(v.get("datum_eerste_tenaamstelling_in_nederland"))
    r.last_owner_change = _date(v.get("datum_tenaamstelling"))
    if r.first_admission and r.first_nl_registration:
        r.imported = r.first_admission != r.first_nl_registration
    code = v.get("code_toelichting_tellerstandoordeel")
    r.odometer_code = code
    verdict, note = ODOMETER_CODES.get(code or "", (v.get("tellerstandoordeel"), ""))
    r.odometer_verdict, r.odometer_note = verdict, note
    r.odometer_last_year = v.get("jaar_laatste_registratie_tellerstand")
    r.open_recall = _yes(v.get("openstaande_terugroepactie_indicator"))
    r.apk_expiry = _date(v.get("vervaldatum_apk"))
    r.exported = _yes(v.get("export_indicator"))
    r.insured = _yes(v.get("wam_verzekerd"))
    price = v.get("catalogusprijs")
    r.catalogue_price = int(price) if price and price.isdigit() else None
    r.recalls = [{"ref": x.get("referentiecode_rdw"), "status": x.get("status"),
                  "code": x.get("code_status")} for x in (recalls or [])]
    if code in ("04", "07"):
        r.red_flags.append(f"odometer verdict {verdict}: {note}")
    if r.open_recall:
        r.red_flags.append("open recall: ask whether it is booked; check for interim restrictions")
    if r.exported:
        r.red_flags.append("export indicator set: car already deregistered for export")
    return r


def _get(dataset: str, plate: str, fetch: Fetch | None, timeout: float) -> list[dict]:
    q = urllib.parse.urlencode({"kenteken": plate})
    url = f"{BASE}/{dataset}.json?{q}"
    raw = fetch(url) if fetch else urllib.request.urlopen(url, timeout=timeout).read()
    return json.loads(raw)


def lookup(plate: str, *, fetch: Fetch | None = None, timeout: float = 20) -> RdwReport:
    p = normalize_plate(plate)
    vehicles = _get(VEHICLES, p, fetch, timeout)
    recalls = _get(RECALLS, p, fetch, timeout) if vehicles else []
    return parse(p, vehicles, recalls)
