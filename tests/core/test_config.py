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


def test_free_form_maps_take_any_key(write_config):
    write_config({"owner": {"tz": "UTC"}, "sites": {"overrides": {"new-site.example": {"pace": {"min_gap_s": 30}}}},
                  "search": {"options_wanted": {"any_option": 2}}, "contact": {"persona": {"any_line": "x"}}})
    assert config.load().get("sites.overrides")["new-site.example"]["pace"]["min_gap_s"] == 30


@pytest.mark.parametrize("data, needle", [
    ({"owner": {"tz": "UTC"}, "notfy": {}}, "notfy"),
    ({"owner": {"tz": "Mars/Base"}}, "owner.tz"),
    ({"owner": {}}, "tz"),
    ({"owner": {"tz": "UTC"}, "notify": {"quiet_hours": "21:30-25:00"}}, "notify.quiet_hours"),
    ({"owner": {"tz": "UTC"}, "notify": {"backend": "pigeon"}}, "notify.backend"),
    ({"owner": {"tz": "UTC"}, "cardb": {"token": "plaintext-token"}}, "cardb.token"),
    ({"owner": {"tz": "UTC"}, "secrets": {"backend": "vault"}}, "secrets.backend"),
    # strict sections: a typo is an error, not a silently ignored key
    ({"owner": {"tz": "UTC"}, "contact": {"quiet_hour": "01:30-08:10"}}, "contact"),
    ({"owner": {"tz": "UTC"}, "notify": {"extra": True}}, "notify"),
    ({"owner": {"tz": "UTC"}, "browsers": {"captcha": {"enable": True}}}, "browsers.captcha"),
    ({"owner": {"tz": "UTC"}, "sites": {"overrides": {"mobile.de": {"pace": {"per_hour": 5}}}}}, "sites.overrides.mobile.de.pace"),
    ({"owner": {"tz": "UTC"}, "search": {"hard_filters": [{"flag": "damaged", "exclude": True}]}}, "search.hard_filters.0"),
    ({"owner": {"tz": "UTC"}, "search": {"hard_filters": [{"field": "km", "fact": "x", "max": 1}]}}, "search.hard_filters.0"),
    ({"owner": {"tz": "UTC"}, "contact": {"nudge": {"exclude": [{"field": "tier", "eq": 3, "whyy": "x"}]}}}, "contact.nudge.exclude.0"),
    ({"owner": {"tz": "UTC"}, "orchestrate": {"schedule": {"sweep": "7am"}}}, "orchestrate.schedule.sweep"),
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
