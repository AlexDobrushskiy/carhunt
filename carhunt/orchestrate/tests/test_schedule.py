import plistlib

import pytest

from carhunt.orchestrate import schedule


def test_jobs_from_config(config):
    jobs = {j["label"]: j for j in schedule.jobs(config)}
    assert set(jobs) == {"carhunt.sweep", "carhunt.unpause", "carhunt.digest-morning", "carhunt.digest-evening",
                         "carhunt.pause", "carhunt.learning", "carhunt.cleanup"}
    assert jobs["carhunt.pause"]["argv"] == ["pause", "--night"] and jobs["carhunt.pause"]["times"] == ["23:00"]
    assert jobs["carhunt.digest-evening"]["argv"] == ["digest", "--slot", "evening"]


def test_plist_shape(home, config):
    plists = schedule.render_all(config, exe="/opt/carhunt/bin/carhunt")
    d = plistlib.loads(plists["carhunt.learning"])
    assert d["ProgramArguments"] == ["/opt/carhunt/bin/carhunt", "learn", "start"]
    assert d["StartCalendarInterval"] == {"Hour": 23, "Minute": 15}
    assert d["EnvironmentVariables"]["CARHUNT_HOME"] == str(home)
    assert d["EnvironmentVariables"]["PATH"].startswith("/opt/carhunt/bin:")
    assert plistlib.loads(plists["carhunt.cleanup"])["StartInterval"] == 1800


def test_bad_time_and_unknown_job(config):
    config["orchestrate"]["schedule"]["pause"] = "25:00"
    with pytest.raises(schedule.ScheduleError, match="bad time"):
        schedule.jobs(config)
    config["orchestrate"]["schedule"] = {"weird": "10:00"}
    with pytest.raises(schedule.ScheduleError, match="schedule_commands"):
        schedule.jobs(config)
    config["orchestrate"]["schedule_commands"] = {"weird": ["digest", "--dry-run"]}
    assert schedule.jobs(config)[0]["argv"] == ["digest", "--dry-run"]


def test_install_uninstall_without_launchctl(home, config, tmp_path, monkeypatch):
    monkeypatch.setenv("CARHUNT_LAUNCHAGENTS_DIR", str(tmp_path / "LaunchAgents"))
    (tmp_path / "LaunchAgents").mkdir()
    (tmp_path / "LaunchAgents" / "com.other.job.plist").write_text("x")
    written = schedule.install(config, load=False, exe="/x/carhunt")
    assert len(written) == 7 and all(p.name.startswith("carhunt.") for p in written)
    assert all("[installed]" in line for line in schedule.show(config))
    schedule.uninstall(unload=False)
    assert [p.name for p in (tmp_path / "LaunchAgents").iterdir()] == ["com.other.job.plist"]
