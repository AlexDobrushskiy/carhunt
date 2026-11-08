"""carsbat.com: VIN/lot URL helpers, URL ownership/lot id, Unsupported readers (README-only site)."""
import pytest

from carhunt.sites import base
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet

VIN = "SYNAB12CD3E456789"
LOT = f"https://carsbat.com/en/detail/{VIN.lower()}-abc12x/"


def site():
    return base.get("carsbat.com", net=FakeNet("carsbat.com"))


def test_vin_helpers():
    s = site()
    assert s.vin_search_url(" synab12cd3e456789 ") == f"https://carsbat.com/en/vin-search/?query={VIN}"
    assert s.lot_vin(LOT) == VIN and s.lot_vin("https://www.example.invalid/en/detail/x/") is None
    with pytest.raises(ValueError):   # I/O/Q never appear in a VIN
        s.vin_search_url("SYNAB12CD3E45678O")


def test_owns_and_lot_id():
    s = site()
    assert s.owns(LOT) and s.owns("https://www.carsbat.com/en/") and s.meta["kind"] == "vin-history"
    assert s.ad_id(LOT) == f"{VIN.lower()}-abc12x"
    assert base.for_url(LOT).id == "carsbat.com"


@pytest.mark.parametrize("call", [lambda s: s.lookup(VIN), lambda s: s.ad(LOT), lambda s: s.is_live(LOT),
                                  lambda s: list(s.search(SearchQuery(make="Kia", model="EV6")))])
def test_readers_unsupported(call):
    s = site()
    with pytest.raises(base.Unsupported):
        call(s)
    assert s.net.calls == []
