"""VIN decode + check digit on synthetic VINs (built by concatenation, never real ones)."""
import pytest

from carhunt.vet import vin


def make(wmi: str, vds: str, my: str, plant: str, serial: str = "000123") -> str:
    return wmi + vds + my + plant + serial


def test_check_digit_hand_computed():
    # S=2*8 Y=8*7 N=5*6 0*5 0*4 0*3 0*2 0*10 | 0*0 | A=1*9 B=2*8 C=3*7 1*6 2*5 3*4 4*3 5*2
    # = 16+56+30 + 9+16+21+6+10+12+12+10 = 198; 198 % 11 = 0
    v = "SYN" + "00000" + "0" + "ABC" + "12345"
    assert vin.check_digit(v) == "0"
    # vary the last char (weight 2); remainder 10 must come out as "X"
    for last in "0123456789":
        w = v[:16] + last
        total = 198 - 5 * 2 + int(last) * 2
        assert vin.check_digit(w) == ("X" if total % 11 == 10 else str(total % 11))


def test_with_check_digit_roundtrip():
    v = vin.with_check_digit(make("1FA", "BP0CE0", "L", "F", "100001"))
    assert vin.check_digit(v) == v[8]
    info = vin.decode(v, ref_year=2026)
    assert info.check_digit["valid"] and info.check_digit["mandatory"]


def test_invalid_check_digit_red_for_north_america():
    good = vin.with_check_digit(make("1FA", "BP0CE0", "L", "F", "100001"))
    bad = good[:8] + ("1" if good[8] != "1" else "2") + good[9:]
    info = vin.decode(bad, ref_year=2026)
    codes = {f.code: f.severity for f in info.flags}
    assert codes["check_digit_invalid"] == "red"
    assert codes["north_america"] == "warn"
    assert info.model_year == 2020  # position 7 letter -> 2010+ cycle


def test_eu_vag_decode_and_flags():
    v = make("WVG", "ZZZE2Z", "S", "P", "000001")
    info = vin.decode(v, first_reg="2024-10", ref_year=2026)
    assert info.valid_format
    assert info.manufacturer.startswith("Volkswagen")
    assert info.country == "Germany" and info.region == "Europe"
    assert info.model_year == 2025
    assert not info.check_digit["mandatory"]
    codes = {f.code for f in info.flags}
    assert "vag_europe" in codes
    assert "model_year_mismatch" not in codes
    assert not info.red


def test_model_year_mismatch_flag():
    v = make("WVG", "ZZZE2Z", "S", "P", "000001")
    info = vin.decode(v, first_reg="2019-01", ref_year=2026)
    assert "model_year_mismatch" in {f.code for f in info.flags}


def test_china_jv_red_flag():
    v = vin.with_check_digit(make("LFV", "BA24G0", "N", "3", "000001"))
    info = vin.decode(v, ref_year=2026)
    assert info.country == "China"
    assert "china_market" in {f.code for f in info.flags}
    assert info.red


def test_china_built_export_is_info_only():
    v = vin.with_check_digit(make("LRW", "YGDEE0", "R", "C", "000001"))
    info = vin.decode(v, ref_year=2026)
    flags = {f.code: f.severity for f in info.flags}
    assert flags.get("china_built") == "info"
    assert not info.red


@pytest.mark.parametrize("bad, err", [
    ("SYN123", "length"),
    ("SYNIOQ" + "0" * 11, "invalid characters"),
])
def test_invalid_format(bad, err):
    info = vin.decode(bad)
    assert not info.valid_format
    assert any(err in e for e in info.errors)
    assert info.red


def test_normalize_strips_spaces_and_case():
    raw = "wvg zzz-e2z s p 000001"
    assert vin.normalize(raw) == make("WVG", "ZZZE2Z", "S", "P", "000001")


def test_model_year_candidates():
    assert vin.model_year_candidates("A") == [1980, 2010]
    assert vin.model_year_candidates("9") == [2009, 2039]
    assert vin.model_year_candidates("Q") == []


def test_vpic_parses_injected_payload():
    payload = b'{"Results":[{"Make":"SYNMAKE","Model":"","ModelYear":"2020","ErrorCode":"0"}]}'
    out = vin.vpic(make("1FA", "BP0CE0", "L", "F", "100001"), fetch=lambda url: payload)
    assert out == {"Make": "SYNMAKE", "ModelYear": "2020"}
