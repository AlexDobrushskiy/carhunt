import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_dry_run_lists_every_step_and_changes_nothing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CARHUNT_", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), CARHUNT_HOME=str(home / ".carhunt"))
    r = subprocess.run([str(REPO / "scripts/bootstrap"), "--dry-run", "--skip-mcp"], capture_output=True,
                       text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    steps = re.findall(r"^\[(\d+)/(\d+)\] (.+)$", r.stdout, re.M)
    assert [int(n) for n, _, _ in steps] == list(range(1, int(steps[0][1]) + 1))
    titles = " | ".join(t for _, _, t in steps)
    for needle in ("Prerequisites", "Homebrew", "venv", "PATH", "cardb", "Web UI", "Run-data home", "Config",
                   "cardb init", "compose", "skills", "Browsers", "guard hooks", "privacy hooks", "Doctor"):
        assert needle in titles, needle
    assert "dry run done" in r.stdout
    assert not (home / ".carhunt").exists() and not (home / ".local").exists() and not (home / ".claude").exists()


def test_unknown_option_is_usage_error():
    r = subprocess.run([str(REPO / "scripts/bootstrap"), "--bogus"], capture_output=True, text=True)
    assert r.returncode == 2 and "usage" in r.stderr
