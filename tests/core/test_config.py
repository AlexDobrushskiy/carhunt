import pytest

from carhunt.core import config


def test_example_config_is_valid(example_config):
    cfg = config.load()
    assert cfg.get("owner.tz")
    assert cfg.source == example_config


def test_secret_refs_stay_refs(example_config, monkeypatch):
    cfg = config.load()
    ref = cfg.get("notify.telegram.bot_token")
    assert isinstance(ref, config.SecretRef) and str(ref) == "secret:telegram_bot_token"
    assert cfg.as_dict()["notify"]["telegram"]["bot_token"] == "secret:telegram_bot_token"
    monkeypatch.setenv("CARHUNT_SECRET_TELEGRAM_BOT_TOKEN", "value-xyz")
    assert cfg.secret("notify.telegram.bot_token") == "value-xyz"
    # nothing that renders the config shows the value
    assert "value-xyz" not in repr(cfg) + str(cfg.as_dict()) + repr(cfg.section("notify"))


def test_unknown_key_inside_module_section_is_allowed(write_config):
    write_config({"owner": {"tz": "UTC"}, "contact": {"brand_new_key": 1}, "notify": {"extra": True}})
    assert config.load().get("contact.brand_new_key") == 1


@pytest.mark.parametrize("data, needle", [
    ({"owner": {"tz": "UTC"}, "notfy": {}}, "notfy"),
    ({"owner": {"tz": "Mars/Base"}}, "owner.tz"),
    ({"owner": {}}, "tz"),
    ({"owner": {"tz": "UTC"}, "notify": {"quiet_hours": "21:30-25:00"}}, "notify.quiet_hours"),
    ({"owner": {"tz": "UTC"}, "notify": {"backend": "pigeon"}}, "notify.backend"),
    ({"owner": {"tz": "UTC"}, "cardb": {"token": "plaintext-token"}}, "cardb.token"),
    ({"owner": {"tz": "UTC"}, "secrets": {"backend": "vault"}}, "secrets.backend"),
])
def test_invalid_configs(write_config, data, needle):
    write_config(data)
    with pytest.raises(config.ConfigError) as e:
        config.load()
    assert needle in str(e.value)


def test_missing_config_says_how_to_fix(carhunt_env):
    with pytest.raises(config.ConfigError, match="bootstrap"):
        config.load()
    assert config.load_or_none() is None


def test_carhunt_config_env_overrides_path(tmp_path, monkeypatch, write_config):
    f = tmp_path / "other.yaml"
    f.write_text("owner: {tz: UTC, name: other}\n")
    monkeypatch.setenv("CARHUNT_CONFIG", str(f))
    assert config.load().get("owner.name") == "other"


def test_path_creates_parents(carhunt_env):
    p = config.path("a", "b", "c.json")
    assert p.parent.is_dir() and p == carhunt_env / "a" / "b" / "c.json"
