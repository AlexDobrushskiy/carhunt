"""RDW parser on synthetic payloads shaped like opendata.rdw.nl m9d7-ebf2 / t49b-isb7."""
import json

from carhunt.vet import rdw

VEHICLE = {
    "kenteken": "SYN01X", "merk": "SYNMAKE", "handelsbenaming": "SYN MODEL",
    "datum_eerste_toelating": "20230315", "datum_eerste_tenaamstelling_in_nederland": "20240110",
    "datum_tenaamstelling": "20250601", "tellerstandoordeel": "Geen oordeel",
    "code_toelichting_tellerstandoordeel": "05", "jaar_laatste_registratie_tellerstand": "2025",
    "openstaande_terugroepactie_indicator": "Ja", "vervaldatum_apk": "20270315",
    "export_indicator": "Nee", "wam_verzekerd": "Ja", "catalogusprijs": "50000",
}
RECALL = {"kenteken": "SYN01X", "referentiecode_rdw": "SYN0001", "status": "Openstaand", "code_status": "O"}


def test_parse_imported_with_open_recall():
    r = rdw.parse("syn-01-x", [VEHICLE], [RECALL])
    assert r.found and r.plate == "SYN01X"
    assert r.first_admission == "2023-03-15" and r.first_nl_registration == "2024-01-10"
    assert r.imported is True
    assert r.odometer_verdict == "no verdict"
    assert r.open_recall is True and r.recalls[0]["status"] == "Openstaand"
    assert r.insured is True and r.exported is False and r.catalogue_price == 50000
    assert any("open recall" in f for f in r.red_flags)
    assert "imported" in r.fact_value()


def test_parse_illogical_odometer_is_red_flag():
    v = dict(VEHICLE, code_toelichting_tellerstandoordeel="04", openstaande_terugroepactie_indicator="Nee",
             datum_eerste_tenaamstelling_in_nederland="20230315")
    r = rdw.parse("SYN01X", [v])
    assert r.imported is False
    assert r.odometer_verdict == "ILLOGICAL"
    assert len(r.red_flags) == 1 and "rollback" in r.red_flags[0]


def test_not_found():
    r = rdw.parse("SYN01X", [])
    assert not r.found and "not found" in r.fact_value()


def test_lookup_uses_fetch_and_both_datasets():
    calls = []

    def fetch(url):
        calls.append(url)
        return json.dumps([RECALL] if rdw.RECALLS in url else [VEHICLE]).encode()

    r = rdw.lookup("SYN-01-X", fetch=fetch)
    assert r.found and len(calls) == 2
    assert all("kenteken=SYN01X" in u for u in calls)


def test_lookup_skips_recall_call_when_plate_unknown():
    calls = []
    r = rdw.lookup("SYN01X", fetch=lambda u: calls.append(u) or b"[]")
    assert not r.found and len(calls) == 1
