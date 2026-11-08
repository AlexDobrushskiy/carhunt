import os

import pytest


@pytest.fixture(autouse=True)
def _offline_home(tmp_path, monkeypatch):
    """Tests never touch ~/.carhunt or the real cardb."""
    monkeypatch.setenv("CARHUNT_HOME", str(tmp_path / "carhunt"))
    monkeypatch.delenv("CARHUNT_FAKE_SITES_BLOCK", raising=False)
    yield
