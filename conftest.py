"""Root test isolation for every suite (tests/ and carhunt/<pkg>/tests).

Each test gets a temp $CARHUNT_HOME and the file secrets backend; the real macOS Keychain is blocked
unless the test is marked `keychain` and CARHUNT_TEST_KEYCHAIN=1 (a builder's run once wrote to it).
"""
import os
import tempfile

import pytest

KEEP = {"CARHUNT_TEST_CHROME", "CARHUNT_TEST_KEYCHAIN", "CARHUNT_CHROME", "CARHUNT_PYTHON", "CARHUNT_NODE", "CARDB_BIN"}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "keychain: touches the real Keychain; runs only with CARHUNT_TEST_KEYCHAIN=1")
    # process-wide too, so import-time code and subprocesses never see the user's home or Keychain
    for k in list(os.environ):
        if k.startswith(("CARHUNT_", "CARDB_")) and k not in KEEP:
            del os.environ[k]
    os.environ["CARHUNT_HOME"] = tempfile.mkdtemp(prefix="carhunt-test-home-")
    os.environ["CARHUNT_SECRETS_BACKEND"] = "file"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("CARHUNT_TEST_KEYCHAIN") == "1":
        return
    skip = pytest.mark.skip(reason="real Keychain test; set CARHUNT_TEST_KEYCHAIN=1")
    for item in items:
        if "keychain" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _carhunt_isolation(tmp_path, monkeypatch, request):
    for k in list(os.environ):
        if k.startswith(("CARHUNT_", "CARDB_")) and k not in KEEP:
            monkeypatch.delenv(k)
    home = tmp_path / "_root_home" / "carhunt"
    home.mkdir(parents=True)
    monkeypatch.setenv("CARHUNT_HOME", str(home))
    monkeypatch.setenv("CARHUNT_SECRETS_BACKEND", "file")
    if "keychain" not in request.keywords:
        from carhunt.core import secrets

        def _blocked(self, *a, **kw):
            raise RuntimeError("real Keychain is blocked in tests (mark the test `keychain`)")

        monkeypatch.setattr(secrets.KeychainBackend, "_run", _blocked)
