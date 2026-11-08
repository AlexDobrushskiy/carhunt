import re

import pytest

from carhunt.orchestrate import launch

from .conftest import REPO

TEMPLATES = sorted((REPO / "agents" / "templates").glob("*.md"))
ROLES = sorted(p.parent.name for p in (REPO / "agents" / "roles").glob("*/brief.md"))
SECRETISH = re.compile(r"(secret|token|password|api_key|credential|oauth)", re.I)


def test_orchestrate_roles_exist():
    assert {"overseer", "learning"} <= set(ROLES)


@pytest.mark.parametrize("role", ROLES)
def test_role_brief_renders_fully(home, config, role):
    text = launch.compose(role, config, f"carhunt-{role}")
    assert launch.unrendered(text) == []
    assert "{agent." not in text and "{owner." not in text
    assert str(home / "agents" / role) in text or role == "learning" or "{agent.dir}" not in text


@pytest.mark.parametrize("tmpl", TEMPLATES, ids=lambda p: p.name)
def test_template_placeholders_are_known_and_not_secret(home, config, tmpl):
    v = launch.variables(config, "x", "carhunt-x", {"task.name": "t", "task.body": "b"})
    keys = launch.PLACEHOLDER.findall(tmpl.read_text())
    assert [k for k in keys if k not in v] == []
    assert [k for k in keys if SECRETISH.search(k)] == []


def test_secret_values_never_rendered(home, config, monkeypatch, role="overseer"):
    monkeypatch.setenv("CARHUNT_SECRET_TELEGRAM_BOT_TOKEN", "123456789:SYNTHETICxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    config["cardb"]["token"] = "secret:cardb_token"
    text = launch.compose(role, config, "carhunt-overseer")
    assert "SYNTHETICxxxx" not in text
    assert "secret:" not in text


def test_render_rules():
    assert launch.render("a {x.y} {{lit}} {\"k\": 1}", {"x.y": "1"}) == 'a 1 {lit} {"k": 1}'
    with pytest.raises(launch.LaunchError, match="nope"):
        launch.render("{nope}", {})


def test_side_task_renders(home, config, fake):
    sid = launch.side_task("probe", "Do: check {braces} stay literal.\nDone: report.", backend=fake, config=config)
    brief = (home / "agents" / "side-probe" / "brief.md").read_text()
    assert "Side task: probe" in brief and "{braces} stay literal" in brief
    assert fake.sessions[sid]["env"]["CARHUNT_AGENT"] == "side-probe"


def test_learned_rules_appended_verbatim(home, config, dummy_role):
    (home / "learned").mkdir()
    (home / "learned" / "dummy.md").write_text("## Waits (learning, 2026-11-07)\n- keep {this} literal\n")
    text = launch.compose("dummy", config, "carhunt-dummy")
    assert text.index("Common rules") < text.index("Dummy dummy") < text.index("keep {this} literal")


def test_digest_template_renders():
    tmpl = (REPO / "agents" / "templates" / "digest.txt").read_text()
    keys = set(launch.PLACEHOLDER.findall(tmpl))
    assert keys == {"slot", "date", "sessions", "cars", "needs_you", "advice", "fyi"}
