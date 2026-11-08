import json
import uuid
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]


class FakeBackend:
    """In-memory session backend: records spawns, sends, closes."""

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.sent: list[tuple[str, str, bool]] = []
        self.closed: list[str] = []

    def spawn(self, name, cwd, cmd, env, after=None):
        sid = str(uuid.uuid4()).upper()
        self.sessions[sid] = {"name": name, "cwd": cwd, "cmd": cmd, "env": dict(env), "after": after,
                              "alive": True, "screen": "❯ \n ctx:12% \n", "ctx": 12}
        return sid

    def send(self, sid, text, interrupt=False):
        self.sent.append((sid, text, interrupt))
        return "mailbox"

    def screen(self, sid, lines=40):
        return self.sessions[sid]["screen"]

    def ctx_percent(self, sid):
        return self.sessions[sid]["ctx"]

    def close(self, sid):
        self.sessions[sid]["alive"] = False
        self.closed.append(sid)

    def alive(self, sid):
        return sid in self.sessions and self.sessions[sid]["alive"]


@pytest.fixture
def example_config():
    return yaml.safe_load((REPO / "config.example.yaml").read_text())


@pytest.fixture
def home(tmp_path, monkeypatch, example_config):
    h = tmp_path / "carhunt"
    h.mkdir()
    for k in ("CARHUNT_CONFIG", "CARHUNT_SESSION_ID", "AGTERM_SESSION_ID", "CARHUNT_AGENT", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CARHUNT_HOME", str(h))
    monkeypatch.setenv("CARHUNT_REPO", str(REPO))
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T12:00:00")
    (h / "config.yaml").write_text(yaml.safe_dump(example_config))
    return h


@pytest.fixture
def config(home):
    from carhunt.orchestrate import settings
    return settings.load()


@pytest.fixture
def fake():
    return FakeBackend()


@pytest.fixture
def dummy_role(home):
    d = home / "roles" / "dummy"
    d.mkdir(parents=True)
    (d / "brief.md").write_text("# Dummy {agent.role}\nWrite done: `carhunt state done`, then stop.\n")
    return "dummy"


def read_state(home, role):
    return json.loads((home / "agents" / role / "state.json").read_text())
