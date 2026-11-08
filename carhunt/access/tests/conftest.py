import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "chrome: launches a real Chrome (smoke); runs only with CARHUNT_TEST_CHROME=1")


@pytest.fixture
def carhunt_home(tmp_path, monkeypatch):
    """A throwaway $CARHUNT_HOME (never ~/.carhunt), with no config file."""
    home = tmp_path / "carhunt"
    home.mkdir()
    monkeypatch.setenv("CARHUNT_HOME", str(home))
    monkeypatch.setenv("CARHUNT_CONFIG", str(home / "config.yaml"))
    return home


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """No CARHUNT_* from the outer shell; temp home; file secrets so tests never touch the real Keychain."""
    keep = {"CARHUNT_TEST_CHROME", "CARHUNT_CHROME", "CARHUNT_PYTHON", "CARHUNT_NODE"}
    for k in list(os.environ):
        if k.startswith(("CARHUNT_", "CARDB_")) and k not in keep:
            monkeypatch.delenv(k)
    home = tmp_path / "_home" / "carhunt"
    home.mkdir(parents=True)
    monkeypatch.setenv("CARHUNT_HOME", str(home))
    monkeypatch.setenv("CARHUNT_SECRETS_BACKEND", "file")
