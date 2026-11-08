"""PR-code mapping against the bundled VW-group table."""
from carhunt.vet import prcodes


def test_table_loads_and_groups_rows():
    t = prcodes.table("vag")
    assert len(t) > 50
    assert len(t["PYY"]) >= 2  # a package code implies several options


def test_decode_known_codes():
    dec, unknown = prcodes.decode(["3FU, 4E7 / 9M3", "ZZ9"])
    opts = prcodes.options(dec)
    assert opts["pano"] == ("yes", "3FU")
    assert opts["power_tailgate"] == ("yes", "4E7")
    assert opts["heat_pump"] == ("yes", "9M3")
    assert unknown == ["ZZ9"]


def test_none_code_maps_to_no_and_yes_wins():
    opts = prcodes.options(prcodes.decode(["3FA"])[0])
    assert opts["pano"][0] == "no"
    both = prcodes.options(prcodes.decode(["3FA", "3FU"])[0])
    assert both["pano"] == ("yes", "3FU")


def test_package_expands_to_several_options():
    opts = prcodes.options(prcodes.decode(["PYY"])[0])
    assert opts["electric_seats"][0] == "yes" and opts["memory_seats"][0] == "yes"


def test_cardb_args_and_dedupe():
    dec, _ = prcodes.decode(["9M3", "9m3"])
    assert prcodes.cardb_args(dec) == ["heat_pump=yes:vin_pr_code:9M3"]


def test_unknown_brand():
    import pytest
    with pytest.raises(FileNotFoundError):
        prcodes.table("nobrand")
