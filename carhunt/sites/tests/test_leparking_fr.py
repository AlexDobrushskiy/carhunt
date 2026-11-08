"""leparking.fr: list URL, filter JS, URL ownership/row id, Unsupported readers (README-only site)."""
import pytest

from carhunt.sites import base
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet

ROW = "https://www.leparking.fr/tools/900000001/0/P/P.html"


def site():
    return base.get("leparking.fr", net=FakeNet("leparking.fr"))


def test_query_builder_and_filter_js():
    s = site()
    q = SearchQuery(make="Toyota", model="bZ4X", country="FR", seller="private")
    assert s.search_url(q) == "https://www.leparking.fr/voiture-occasion/toyota-bz4x.html"
    assert s.filter_js(q) == ("ctrl.set_criteria('id_pays',18,'FRANCE',window); "
                              "ctrl.set_criteria('id_vendeur',1,'Particuliers',window); ctrl.need_refresh()")
    assert s.filter_js(SearchQuery(make="Toyota", model="bZ4X")) == "ctrl.need_refresh()"


@pytest.mark.parametrize("call", [
    lambda s: s.search_url(SearchQuery(make="Kia", model="EV6")),
    lambda s: s.search_url(SearchQuery(make="Toyota", model="bZ4X"), page=2),
    lambda s: s.filter_js(SearchQuery(country="DE")),
    lambda s: s.filter_js(SearchQuery(seller="dealer")),
    lambda s: list(s.search(SearchQuery(make="Toyota", model="bZ4X"))),
    lambda s: s.ad(ROW),
    lambda s: s.is_live(ROW),
])
def test_unsupported(call):
    s = site()
    with pytest.raises(base.Unsupported):
        call(s)
    assert s.net.calls == []


def test_owns_and_row_id():
    s = site()
    assert s.owns(ROW) and s.ad_id(ROW) == "900000001"
    assert s.source_redirect_url("900000001") == ROW
    assert base.for_url(ROW).id == "leparking.fr"
