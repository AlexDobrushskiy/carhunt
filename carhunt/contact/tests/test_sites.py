"""Marketplace senders: dry runs, text refusals, and send/verify/read against local fake pages.

Offline: every request from the test browser is answered from tests/fixtures/sites/ or aborted;
URLs and texts are synthetic.
"""
from __future__ import annotations

import contextlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from carhunt.contact.channels import get, site_names
from carhunt.contact.channels.base import DELIVERED, FAILED, UNKNOWN, ChannelError

FIX = Path(__file__).parent / "fixtures" / "sites"
ALL_SITES = ["autoscout24", "coches.net", "custojusto.pt", "kleinanzeigen.de", "leboncoin.fr", "mobile.de",
             "olx.pt", "standvirtual.com", "subito.it", "wallapop.com"]
PERSONA = {"name": "Buyer Example", "email": "buyer+cars@example.com", "aliases": ["Buyer"]}
CFG = {"contact": {"persona": PERSONA}}


def no_tab(*_a, **_k):
    raise AssertionError("dry run must not open a browser")


def fast(ch):
    ch.load_ms, ch.settle_ms, ch.box_timeout_ms = 300, 800, 3000
    return ch


# ---------------------------------------------------------------- no browser

def test_registry_lists_every_site():
    assert set(ALL_SITES) <= set(site_names())


@pytest.mark.parametrize("site", ALL_SITES)
def test_dry_run_never_opens_a_tab(site):
    ch = get(site, CFG, tab_factory=no_tab)
    out = ch.dry_run("https://ads.example.invalid/ad/1", "Hola, ¿sigue disponible?")
    assert out["channel"] == site and out["submit"] is False and out["route"] == ch.route
    assert out["text"] == "Hola, ¿sigue disponible?"


@pytest.mark.parametrize("site", ALL_SITES)
@pytest.mark.parametrize("text", ["see https://ads.example.invalid/ad/1", "www.example.invalid/ad"])
def test_url_in_text_is_refused(site, text):
    assert "URL" in get(site, CFG).check_text(text)


def test_wallapop_caps_at_300_chars():
    ch = get("wallapop.com", CFG)
    assert ch.check_text("a" * 300) is None
    assert "max 300" in ch.check_text("a" * 301)


def test_routes_and_countries():
    assert (get("coches.net").route, get("coches.net").country) == ("camoufox", "ES")
    assert (get("leboncoin.fr").route, get("leboncoin.fr").country) == ("plain-chrome", "FR")
    assert get("mobile.de").route == "identity"


def test_autoscout24_de_form_refused_without_a_browser():
    ch = get("autoscout24", CFG, tab_factory=no_tab)
    r = ch.send("https://www.autoscout24.de/angebote/synthetic-1", "Hallo, noch verfügbar?")
    assert not r.ok and r.raw["refused"] == "broken_form"
    assert ch.verify("x", "y", r) == FAILED


@pytest.mark.parametrize("site", ["autoscout24", "coches.net"])
def test_read_thread_unsupported_where_replies_come_by_mail(site):
    with pytest.raises(ChannelError):
        get(site, CFG, tab_factory=no_tab).read_thread("https://ads.example.invalid/ad/1")


def test_leboncoin_reply_url():
    ch = get("leboncoin.fr")
    assert ch.target_url(None, "https://www.leboncoin.fr/ad/voitures/1234567") == "https://www.leboncoin.fr/reply/1234567"
    assert ch.target_url(None, "https://www.leboncoin.fr/messages/id/c1") == "https://www.leboncoin.fr/messages/id/c1"


def test_selector_override_from_config():
    ch = get("olx.pt", {"contact": {"sites": {"olx.pt": {"selectors": {"box": "#composer"}}}}})
    assert ch.s("box") == "#composer" and ch.s("msg_sel").startswith("[aria-label")


# ---------------------------------------------------------------- fake pages

@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync_api.sync_playwright().start()
    except Exception as e:  # pragma: no cover
        pytest.skip(f"playwright can't start: {e}")
    try:
        b = pw.chromium.launch(headless=True)
    except Exception as e:  # pragma: no cover
        pw.stop()
        pytest.skip(f"chromium can't launch: {e}")
    yield b
    b.close()
    pw.stop()


class FakeSite:
    """Tab factory: a fresh context whose every request is served from fixtures (regex on path+query)
    or aborted. Records posts to /__submit and the opened tabs."""

    def __init__(self, browser, routes, mode="ok", api_status=200):
        self.browser, self.routes, self.mode, self.api_status = browser, routes, mode, api_status
        self.submits: list[str] = []
        self.posts: list[str] = []
        self.calls: list[tuple] = []

    def __call__(self, route, *, country=None, site=None):
        self.calls.append((route, country, site))
        return self._tab()

    @contextlib.contextmanager
    def _tab(self):
        ctx = self.browser.new_context()
        ctx.route("**/*", self._handle)
        try:
            yield ctx.new_page()
        finally:
            ctx.close()

    def _handle(self, route, request):
        u = request.url
        path = re.sub(r"^https?://[^/]+", "", u)
        if request.method == "POST":
            self.posts.append(path)
            if path.startswith("/__submit"):
                self.submits.append(request.post_data or "")
            status = self.api_status if "/contact-mail" in path else 200
            return route.fulfill(status=status, body="{}", content_type="application/json")
        for pat, name in self.routes:
            if re.search(pat, path):
                html = (FIX / name).read_text().replace("__MODE__", self.mode)
                return route.fulfill(status=200, body=html, content_type="text/html; charset=utf-8")
        return route.abort()


MDE_AD = "https://mobile.example.invalid/fahrzeuge/details.html?id=1000001"
MDE_CONV = "https://mobile.example.invalid/nachrichten/c0000001"
MDE_ROUTES = [(r"^/fahrzeuge/details", "mobile.de/ad.html"), (r"^/checkout/core/", "mobile.de/form.html"),
              (r"^/nachrichten/", "mobile.de/conversation.html")]
WP_ROUTES = [(r"^/app/chat\?itemId=", "wallapop.com/chat.html")]
LBC_ROUTES = [(r"^/reply/", "leboncoin.fr/reply.html"), (r"^/messages/id/", "leboncoin.fr/conversation.html"),
              (r"^/messages$", "leboncoin.fr/inbox.html")]


def site(browser, name, routes, **kw):
    fake = FakeSite(browser, routes, **kw)
    return fast(get(name, CFG, tab_factory=fake)), fake


# mobile.de -----------------------------------------------------------------------------------

def test_mobile_de_form_delivered_phone_kept_private(browser):
    ch, fake = site(browser, "mobile.de", MDE_ROUTES)
    r = ch.send(MDE_AD, "Guten Tag, ist das Auto noch verfügbar?")
    assert r.ok and r.raw["confirmed"], r
    assert ch.verify(MDE_AD, "", r) == DELIVERED
    sent = json.loads(fake.submits[0])
    assert sent == {"message": "Guten Tag, ist das Auto noch verfügbar?", "phone": "", "newsletter": False}
    assert fake.calls == [("identity", None, "mobile.de")]


def test_mobile_de_form_without_success_text_is_unknown(browser):
    ch, fake = site(browser, "mobile.de", MDE_ROUTES, mode="silent")
    r = ch.send(MDE_AD, "Guten Tag, ist das Auto noch verfügbar?")
    assert len(fake.submits) == 1
    assert ch.verify(MDE_AD, "", r) == UNKNOWN


def test_mobile_de_duplicate_refused_without_submit(browser):
    ch, fake = site(browser, "mobile.de", MDE_ROUTES)
    r = ch.send(MDE_CONV, "Guten Tag, ist das Auto noch verfügbar? Gab es Unfälle?")
    assert not r.ok and r.raw["refused"] == "duplicate"
    assert fake.submits == [] and ch.verify(MDE_CONV, "", r) == FAILED


def test_mobile_de_conversation_reply_through_contact_data_warning(browser):
    ch, fake = site(browser, "mobile.de", MDE_ROUTES)
    text = "Danke! Sie erreichen mich unter +351 555 000 111."
    r = ch.send(MDE_CONV, text)
    assert fake.submits == [text]
    assert r.raw["in_thread"] and ch.verify(MDE_CONV, text, r) == DELIVERED


def test_mobile_de_thread(browser):
    ch, _ = site(browser, "mobile.de", MDE_ROUTES)
    msgs = ch.read_thread(MDE_CONV)
    assert [(m.from_me, m.text) for m in msgs] == [
        (True, "Guten Tag, ist das Auto noch verfügbar? Gab es Unfälle?"), (False, "Ja, noch da. Unfallfrei.")]
    assert msgs[1].at == datetime(2026, 11, 1, 10, 30, tzinfo=UTC)
    with pytest.raises(ChannelError):
        ch.read_thread(MDE_AD)  # an ad has no thread


# wallapop ------------------------------------------------------------------------------------

def test_wallapop_delivered(browser):
    ch, fake = site(browser, "wallapop.com", WP_ROUTES)
    r = ch.send("abc123syn", "¿Cuántos kilómetros tiene exactamente?")
    assert fake.submits == ["¿Cuántos kilómetros tiene exactamente?"]
    assert r.raw["in_thread"] and ch.verify("abc123syn", "", r) == DELIVERED


def test_wallapop_no_signal_is_unknown(browser):
    ch, fake = site(browser, "wallapop.com", WP_ROUTES, mode="silent")
    r = ch.send("abc123syn", "¿Cuántos kilómetros tiene exactamente?")
    assert len(fake.submits) == 1 and ch.verify("abc123syn", "", r) == UNKNOWN


def test_wallapop_personal_data_dialog_confirmed(browser):
    ch, fake = site(browser, "wallapop.com", WP_ROUTES)
    r = ch.send("abc123syn", "Mi número es +351 555 000 111, gracias.")
    assert fake.submits == ["Mi número es +351 555 000 111, gracias."]
    assert ch.verify("abc123syn", "", r) == DELIVERED


def test_wallapop_duplicate_refused(browser):
    ch, fake = site(browser, "wallapop.com", WP_ROUTES)
    r = ch.send("abc123syn", "Gracias. ¿Tiene más fotos del interior?")
    assert r.raw.get("refused") == "duplicate" and fake.submits == []


def test_wallapop_thread(browser):
    ch, _ = site(browser, "wallapop.com", WP_ROUTES)
    msgs = ch.read_thread("https://es.wallapop.com/app/chat?itemId=abc123syn")
    assert [(m.from_me, m.text) for m in msgs] == [
        (False, "Hola, sí, sigue disponible."), (True, "Gracias. ¿Tiene más fotos del interior?"),
        (False, "Mañana le envío fotos.")]
    assert [m.at.hour for m in msgs] == [10, 10, 11]


# leboncoin -----------------------------------------------------------------------------------

LBC_AD = "https://www.leboncoin.fr/ad/voitures/1234567"


def test_leboncoin_delivered_and_never_an_offer(browser):
    ch, fake = site(browser, "leboncoin.fr", LBC_ROUTES)
    r = ch.send(LBC_AD, "Bonjour, la voiture est-elle toujours disponible ?")
    assert r.raw["confirmed"] and ch.verify(LBC_AD, "", r) == DELIVERED
    assert fake.calls == [("plain-chrome", "FR", "leboncoin.fr")]
    assert "/__offer" not in fake.posts


def test_leboncoin_no_signal_is_unknown(browser):
    ch, fake = site(browser, "leboncoin.fr", LBC_ROUTES, mode="silent")
    r = ch.send(LBC_AD, "Bonjour, la voiture est-elle toujours disponible ?")
    assert len(fake.submits) == 1 and ch.verify(LBC_AD, "", r) == UNKNOWN


def test_leboncoin_block_stops_before_submit(browser):
    ch, fake = site(browser, "leboncoin.fr", [(r"^/reply/", "leboncoin.fr/blocked.html")])
    r = ch.send(LBC_AD, "Bonjour, toujours disponible ?")
    assert not r.ok and r.raw["blocked"] and fake.submits == []
    assert ch.verify(LBC_AD, "", r) == FAILED


def test_leboncoin_poll_returns_unread_inbound_tail(browser):
    ch, _ = site(browser, "leboncoin.fr", LBC_ROUTES)
    got = ch.poll(datetime(2026, 11, 2, 18, 0, 30, tzinfo=UTC))
    assert [(who.endswith("/messages/id/c0000001"), m.from_me, m.text) for who, m in got] == [
        (True, False, "Vous pouvez passer samedi.")]
    assert got[0][1].sender == "Vendeur A"


# other readers -------------------------------------------------------------------------------

def test_olx_thread_from_aria_labels(browser):
    ch, fake = site(browser, "olx.pt", [(r"^/d/anuncio/.*\?chat=1$", "olx.pt/chat.html")])
    msgs = ch.read_thread("https://olx.example.invalid/d/anuncio/synthetic-IDsyn1.html")
    assert [(m.from_me, m.text) for m in msgs] == [
        (True, "Boa tarde, ainda está disponível?"), (False, "Sim, está disponível."), (False, "Pode vir ver no sábado.")]


def test_custojusto_sendbird_thread(browser):
    ch, _ = site(browser, "custojusto.pt", [(r"^/user/messages\?id=", "custojusto.pt/conversation.html")])
    msgs = ch.read_thread("https://www.custojusto.pt/user/messages?id=syn_1_2")
    assert [(m.from_me, m.text) for m in msgs] == [(True, "Bom dia, o carro ainda está disponível?"),
                                                   (False, "Bom dia, sim.")]


# coches.net: success is the contact API's own answer ----------------------------------------

@pytest.mark.parametrize("status,expect", [(200, DELIVERED), (403, FAILED)])
def test_coches_contact_api_status(browser, status, expect):
    ch, fake = site(browser, "coches.net", [(r"^/segunda-mano/", "coches.net/ad.html")], api_status=status)
    ch.api_wait_s = 10
    r = ch.send("https://coches.example.invalid/segunda-mano/synthetic-1000001-covo.aspx", "Hola, ¿sigue disponible?")
    assert r.raw["api_status"] == status
    assert ch.verify("", "", r) == expect
    assert fake.calls == [("camoufox", "ES", "coches.net")]
