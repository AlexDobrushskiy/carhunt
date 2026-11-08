"""La Centrale: query builder, URL ownership/ad id, Unsupported readers (README-only site)."""
import urllib.parse

import pytest

from carhunt.sites import base
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet

AD = "https://www.lacentrale.fr/auto-occasion-annonce-10000000001.html"


def site():
    return base.get("lacentrale.fr", net=FakeNet("lacentrale.fr"))


def test_query_builder():
    s = site()
    u = s.search_url(SearchQuery(make="Volkswagen", model="ID.4", year_min=2021, km_max=50000, price_max=36000,
                                 fuel="bev", seller="dealer", sort="price"), page=3)
    p = urllib.parse.urlparse(u)
    assert p.netloc == "www.lacentrale.fr" and p.path == "/listing"
    assert dict(urllib.parse.parse_qsl(p.query)) == {
        "makesModelsCommercialNames": "VOLKSWAGEN:ID.4", "energies": "elec", "yearMin": "2021",
        "mileageMax": "50000", "priceMax": "36000", "customerFamilyCodes": "PRO", "sortBy": "priceAsc", "page": "3"}
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(s.search_url(SearchQuery(make="Audi", model="Q4 e-tron")))
                                    .query))
    assert q == {"makesModelsCommercialNames": "AUDI:Q4"}   # newest: site default order, no sortBy


@pytest.mark.parametrize("q", [SearchQuery(make="Kia", model="EV6"), SearchQuery(make="Skoda"),
                               SearchQuery(make="Skoda", model="Enyaq", seller="private"),
                               SearchQuery(make="Skoda", model="Enyaq", country="BE")])
def test_query_unsupported(q):
    with pytest.raises(base.Unsupported):
        site().search_url(q)


def test_owns_and_ad_id():
    s = site()
    assert s.owns(AD) and not s.owns("https://www.leboncoin.fr/ad/voitures/1")
    assert s.ad_id(AD) == "10000000001" and s.ad_url("10000000001") == AD
    assert base.for_url(AD).id == "lacentrale.fr"


def test_readers_unsupported_without_network():
    s = site()
    with pytest.raises(base.Unsupported):
        list(s.search(SearchQuery(make="Volkswagen", model="ID.4")))
    with pytest.raises(base.Unsupported):
        s.ad(AD)
    with pytest.raises(base.Unsupported):
        s.is_live(AD)
    assert s.net.calls == []
