import base64
import importlib
import json
import os
import sys
import time
import types
import urllib.parse
from pathlib import Path

import pytest

from carhunt.access import creds
from carhunt.access.accounts import sms

# the package re-exports the email_code() function under the submodule's name
ec = importlib.import_module("carhunt.access.accounts.email_code")
FIXTURES = Path(__file__).parent / "fixtures" / "access-sites"
REFRESH = "synthetic-refresh-token"


@pytest.fixture
def env(carhunt_home, monkeypatch):
    # + the shared sites/ fixtures: tablefix-alpha has a free-text verification value
    monkeypatch.setenv("CARHUNT_SITES_DIR", f"{FIXTURES}{os.pathsep}{FIXTURES.parent / 'sites'}")
    monkeypatch.setenv("CARHUNT_SECRET_GMAIL_OAUTH_CLIENT",
                       json.dumps({"installed": {"client_id": "cid", "client_secret": "csec"}}))
    monkeypatch.setenv("CARHUNT_SECRET_GMAIL_TOKEN", json.dumps({"refresh_token": REFRESH}))
    return carhunt_home


def _b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


class FakeGmail:
    """Fake HTTP transport for the token endpoint + Gmail API."""

    def __init__(self, messages, token_status=200):
        self.messages, self.token_status, self.calls = messages, token_status, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        if url == ec.TOKEN_URI:
            form = urllib.parse.parse_qs(body.decode())
            assert form["refresh_token"] == [REFRESH] and form["grant_type"] == ["refresh_token"]
            if self.token_status != 200:
                return self.token_status, b'{"error": "invalid_grant"}'
            return 200, json.dumps({"access_token": "at", "expires_in": 3600}).encode()
        assert headers["Authorization"] == "Bearer at"
        path = url.removeprefix(ec.API)
        if path.startswith("messages?"):
            self.query = urllib.parse.parse_qs(path.split("?", 1)[1])["q"][0]
            return 200, json.dumps({"messages": [{"id": m["id"]} for m in self.messages]}).encode()
        mid = path.split("/")[1].split("?")[0]
        return 200, json.dumps(next(m for m in self.messages if m["id"] == mid)).encode()


def _mail(mid, at, text=None, html=None):
    parts = []
    if text:
        parts.append({"mimeType": "text/plain", "body": {"data": _b64(text)}})
    if html:
        parts.append({"mimeType": "text/html", "body": {"data": _b64(html)}})
    return {"id": mid, "internalDate": str(int(at * 1000)),
            "payload": {"mimeType": "multipart/alternative", "parts": parts}}


def test_email_code_from_newest_matching_mail(env):
    now = time.time()
    fake = FakeGmail([_mail("old", now - 3600, text="Your code: 111111"),
                      _mail("new", now, text="Ref #999999. Your code is 482913.")])
    g = ec.Gmail(fake)
    assert ec.email_code("oncefix", since=now - 10, gmail=g) == "482913"  # "#999999" isn't a code
    assert fake.query.startswith("from:(oncefix.example.invalid) after:")  # site.yaml account.mail_from
    assert sum(1 for c in fake.calls if c[1] == ec.TOKEN_URI) == 1  # access token cached


def test_wait_link_reads_hrefs(env):
    now = time.time()
    fake = FakeGmail([_mail("m1", now, html='<p>Hi</p><a href="https://confirm.example.invalid/v?t=abc">ok</a>')])
    url = ec.wait_link("someplace.example.invalid", since=now - 5, pattern=r"https://confirm\.example\.invalid/\S+?(?=\s|$)",
                       gmail=ec.Gmail(fake), sleep=lambda s: None)
    assert url == "https://confirm.example.invalid/v?t=abc"
    assert fake.query.startswith("from:someplace.example.invalid")


def test_wait_code_times_out_to_none(env):
    slept = []
    g = ec.Gmail(FakeGmail([]))
    assert ec.wait_code("oncefix", since=time.time(), timeout=0, gmail=g, sleep=slept.append) is None


def test_token_failure_points_at_production_publish(env):
    with pytest.raises(ec.GmailError, match="In production") as e:
        ec.email_code("oncefix", since=time.time(), gmail=ec.Gmail(FakeGmail([], token_status=400)))
    assert REFRESH not in str(e.value)


def test_gmail_not_configured(carhunt_home, monkeypatch):
    monkeypatch.delenv("CARHUNT_SECRET_GMAIL_TOKEN", raising=False)
    with pytest.raises(ec.GmailError, match="gmail_token"):
        ec.email_code("x", since=time.time(), gmail=ec.Gmail(FakeGmail([])))


# ---------- sms ----------

class FakeSMS(sms.Provider):
    name = "fake"

    def __init__(self, codes=()):
        self.codes, self.rented, self.cancelled = list(codes), [], []

    def success_rates(self, country, service):
        return [("premium", 31.0), ("cheap", 4.0)]

    def rent(self, country, service, *, pool=None):
        self.rented.append(pool)
        return sms.Rental("o1", "+33 555 000 000", country, service, self.name, pool=pool)

    def check(self, rental):
        return self.codes.pop(0) if self.codes else None

    def cancel(self, rental):
        self.cancelled.append(rental.id)
        return True


def test_policy_gate(env):
    assert sms.policy("oncefix").allowed
    p = sms.policy("twofafix")
    assert not p.allowed and "every new-device login" in p.reason
    assert not sms.policy("unknown.example.invalid").allowed  # fail closed
    alpha = sms.policy("tablefix-alpha")  # free-text verification isn't an explicit sms-once
    assert not alpha.allowed and alpha.verification == "email + sms (domestic mobile)"


def test_rent_refuses_sms_2fa_site_before_any_provider_call(env):
    prov = FakeSMS()
    with pytest.raises(sms.PolicyRefused):
        sms.rent("nl", "1", site="twofafix", prov=prov)
    assert prov.rented == []


def test_rent_dry_run_and_best_success_rate(env):
    prov = FakeSMS(codes=[None, "735102"])
    plan = sms.rent("fr", "1", site="oncefix", prov=prov, dry_run=True)
    assert plan["dry_run"] and prov.rented == []
    r = sms.rent("fr", "1", site="oncefix", prov=prov)
    assert prov.rented == ["premium"]  # success rate, not price
    assert sms.wait_code(r, prov=prov, poll=0, sleep=lambda s: None) == "735102"
    assert prov.cancelled == []


def test_wait_code_timeout_cancels_for_refund(env):
    prov = FakeSMS()
    r = sms.rent("fr", "1", site="oncefix", prov=prov)
    with pytest.raises(TimeoutError):
        sms.wait_code(r, prov=prov, timeout=0, sleep=lambda s: None)
    assert prov.cancelled == ["o1"]


def test_smspool_adapter_with_fake_transport(env, monkeypatch):
    key = "synthetic-api-key"
    monkeypatch.setenv("CARHUNT_SECRET_SMS_API_KEY", key)
    calls = []

    def transport(method, url, form):
        calls.append((url, dict(form)))
        if url.endswith("/purchase/sms"):
            return 200, {"success": 1, "order_id": "ABC", "phonenumber": "33555000001", "cost": "2.77"}
        if url.endswith("/sms/check"):
            return 200, {"status": 3, "sms": "482913"}
        if url.endswith("/request/success_rate"):
            return 200, [{"pool": "Charlie", "success_rate": "4"}, {"pool": "Mike", "success_rate": "30"}]
        return 500, {}
    p = sms.SMSPoolProvider(transport=transport)
    assert p.success_rates("fr", "1") == [("Mike", 30.0), ("Charlie", 4.0)]
    r = p.rent("fr", "1", pool="Mike")
    assert (r.id, r.number, r.cost) == ("ABC", "33555000001", 2.77)
    assert p.check(r) == "482913"
    with pytest.raises(sms.SMSError) as e:
        p.cancel(r)
    assert key not in str(e.value) and key not in repr(p)
    assert all(f["key"] == key for _, f in calls)


def test_sms_cli(env, capsys):
    assert sms.main(["policy", "twofafix"]) == 3
    assert capsys.readouterr().out.startswith("REFUSED twofafix")
    assert sms.main(["policy", "oncefix"]) == 0
    capsys.readouterr()
    assert sms.main(["rent", "--site", "oncefix", "--country", "fr", "--service", "1", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert sms.main(["rent", "--site", "twofafix", "--country", "nl", "--service", "1", "--dry-run"]) == 3


# ---------- creds ----------

def test_creds_names_and_login(env, monkeypatch, capsys):
    assert creds.names("https://www.Leboncoin.fr/x") == ("site_leboncoin_fr_user", "site_leboncoin_fr_pass")
    monkeypatch.setenv("CARHUNT_SECRET_SITE_MOBILE_DE_USER", "buyer@example.com")
    monkeypatch.setenv("CARHUNT_SECRET_SITE_MOBILE_DE_PASS", "Synthetic-Pw-1!")
    assert creds.login("mobile.de") == ("buyer@example.com", "Synthetic-Pw-1!")
    with pytest.raises(creds.CredentialsMissing) as e:
        creds.login("coches.net")
    assert "site_coches_net_pass" in str(e.value)
    assert "Synthetic-Pw-1!" not in capsys.readouterr().out


def test_creds_new_stores_never_prints(env, capsys):
    from carhunt.core import secrets
    out = creds.new("coches.net", "buyer@example.com")   # file backend (conftest): never the real Keychain
    pw = secrets.get("site_coches_net_pass")
    assert secrets.get("site_coches_net_user") == "buyer@example.com"
    assert len(pw) == 18 and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw)
    assert pw not in out and pw not in capsys.readouterr().out
    with pytest.raises(ValueError):
        creds.new("coches.net", "")  # no default login


def test_creds_new_refuses_overwrite(env, monkeypatch):
    monkeypatch.setenv("CARHUNT_SECRET_SITE_COCHES_NET_PASS", "live")
    with pytest.raises(FileExistsError):
        creds.new("coches.net", "buyer@example.com")


