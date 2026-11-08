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
