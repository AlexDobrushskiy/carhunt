import os
import stat
import subprocess
import sys
import uuid

import pytest

from carhunt.core import secrets

UNICODE = "pä$$ wörd\nline2 \"q\" \\ 🔑"


def test_file_backend_round_trip(carhunt_env):
    secrets.set("proxy_credentials", "user:pw")
    assert secrets.get("proxy_credentials") == "user:pw"
    assert secrets.exists("proxy_credentials")
    assert secrets.source("proxy_credentials") == "file"
    d = carhunt_env / "secrets"
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    assert stat.S_IMODE((d / "proxy_credentials").stat().st_mode) == 0o600
    secrets.set("proxy_credentials", UNICODE)  # overwrite, odd characters
    assert secrets.get("proxy_credentials") == UNICODE
    assert ("proxy_credentials", "file") in secrets.names()
    assert secrets.delete("proxy_credentials")
    assert not secrets.exists("proxy_credentials")
    with pytest.raises(secrets.SecretNotFound, match="carhunt secret set proxy_credentials"):
        secrets.get("proxy_credentials")


def test_env_wins_over_backend(monkeypatch):
    secrets.set("cardb_token", "from-file")
    monkeypatch.setenv("CARHUNT_SECRET_CARDB_TOKEN", "from-env")
    assert secrets.get("cardb_token") == "from-env"
    assert secrets.source("cardb_token") == "env"
    monkeypatch.setenv("CARHUNT_SECRET_SITE_MOBILE_DE_USER", "u")
    assert secrets.get("site_mobile.de_user") == "u"  # dots map to _ in env names


@pytest.mark.parametrize("bad", ["../etc", "", "a/b", "x" * 80, ".hidden"])
def test_bad_names_rejected(bad):
    with pytest.raises(secrets.SecretError):
        secrets.get(bad)


def test_backend_from_config(write_config, monkeypatch):
    monkeypatch.delenv("CARHUNT_SECRETS_BACKEND")
    write_config({"owner": {"tz": "UTC"}, "secrets": {"backend": "file"}})
    assert secrets.backend().name == "file"
    write_config({"owner": {"tz": "UTC"}, "secrets": {"backend": "op", "op_vault": "v"}})
    b = secrets.backend()
    assert b.name == "op" and b.vault == "v"


@pytest.mark.skipif(sys.platform != "darwin", reason="Keychain is macOS-only")
def test_keychain_round_trip_throwaway_service():
    service = f"carhunt-test-{uuid.uuid4().hex[:10]}"
    kc = secrets.KeychainBackend(service)
    try:
        assert kc.get("tok") is None
        kc.set("tok", "plain-ascii-value")
        assert kc.get("tok") == "plain-ascii-value"
        kc.set("tok", UNICODE)  # -U updates; non-printable goes as b64
        assert kc.get("tok") == UNICODE
        kc.set("other", "x")
        assert kc.names() == ["other", "tok"]
        # the value never shows in the process list: it travels on stdin as hex
        ps = subprocess.run(["ps", "-axo", "args"], capture_output=True, text=True).stdout
        assert "plain-ascii-value" not in ps
    finally:
        kc.delete("tok")
        kc.delete("other")
    assert kc.get("tok") is None and kc.names() == []


def _carhunt(*args, input=None, env=None):
    return subprocess.run([sys.executable, "-m", "carhunt", *args], input=input, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


def test_cli_set_check_ls_exec_never_print_values():
    r = _carhunt("secret", "set", "sms_api_key", input="s3cret-val\n")
    assert r.returncode == 0 and "s3cret-val" not in r.stdout + r.stderr
    assert secrets.get("sms_api_key") == "s3cret-val"  # trailing newline from a pipe dropped
    r = _carhunt("secret", "ls")
    assert "sms_api_key\tfile" in r.stdout and "s3cret-val" not in r.stdout
    assert _carhunt("secret", "check", "sms_api_key").returncode == 0
    r = _carhunt("secret", "check", "sms_api_key", "nope")
    assert r.returncode == 1 and "nope: missing" in r.stdout
    code = "import os; print(len(os.environ['SMS_API_KEY']), os.environ['K'] == 's3cret-val')"
    r = _carhunt("secret", "exec", "sms_api_key", "sms_api_key=K", "--", sys.executable, "-c", code)
    assert r.stdout.split() == ["10", "True"]
    assert _carhunt("secret", "exec", "missing_one", "--", "true").returncode == 1
    assert _carhunt("secret", "rm", "sms_api_key").returncode == 0


def test_cli_has_no_get_command():
    r = _carhunt("secret", "get", "x")
    assert r.returncode == 2  # argparse: invalid choice
