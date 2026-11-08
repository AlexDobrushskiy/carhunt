import os
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def carhunt_env(tmp_path, monkeypatch):
    """Every test gets its own $CARHUNT_HOME; no CARHUNT_* from the outer shell leaks in."""
    for k in list(os.environ):
        if k.startswith(("CARHUNT_", "CARDB_")):
            monkeypatch.delenv(k)
    home = tmp_path / "carhunt"
    home.mkdir()
    monkeypatch.setenv("CARHUNT_HOME", str(home))
    monkeypatch.setenv("CARHUNT_SECRETS_BACKEND", "file")  # never touch the real Keychain by default
    return home


@pytest.fixture
def example_config(carhunt_env):
    dst = carhunt_env / "config.yaml"
    shutil.copy(REPO / "config.example.yaml", dst)
    return dst


@pytest.fixture
def write_config(carhunt_env):
    import yaml

    def _write(data: dict) -> Path:
        dst = carhunt_env / "config.yaml"
        dst.write_text(yaml.safe_dump(data))
        return dst

    return _write
