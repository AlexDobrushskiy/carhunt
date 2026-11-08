import re

import pytest

from carhunt.orchestrate import launch

from .conftest import REPO

TEMPLATES = sorted(p for p in (REPO / "agents" / "templates").glob("*.md") if p.name != "README.md")
ROLES = sorted(p.parent.name for p in (REPO / "agents" / "roles").glob("*/brief.md"))
SECRETISH = re.compile(r"(secret|token|password|api_key|credential|oauth)", re.I)


def test_orchestrate_roles_exist():
    assert {"overseer", "learning"} <= set(ROLES)


# per-launch values (`carhunt agent launch ROLE --var k=v`); synthetic
CAR = ["car=SYN-CAR-1", "vin=SYNVIN0000000001", "country=DE", "destination=PT"]
LAUNCH_VARS = {
    "vet": CAR + ["tasks=vin check, options", "options=heat_pump, pano"],
    "buy": CAR + ["stage=contract"],
}
# a role dir with variants runs as <dir>-<variant>
LAUNCH_ROLES = {"outreach": ["outreach-home", "outreach-abroad"]}


def _launches():
    for d in ROLES:
        for role in LAUNCH_ROLES.get(d, [d]):
            yield pytest.param(role, LAUNCH_VARS.get(d, []), id=role)


@pytest.mark.parametrize("role,var", list(_launches()))
def test_role_brief_renders_fully(home, config, role, var):
    text = launch.compose(role, config, f"carhunt-{role}", extra=launch.parse_vars(var))
    assert launch.unrendered(text) == []
    assert "{agent." not in text and "{owner." not in text
    assert str(home / "agents" / role) in text or role == "learning" or "{agent.dir}" not in text


@pytest.mark.parametrize("role", sorted(LAUNCH_VARS))
def test_per_launch_vars_missing_fail_loudly(home, config, role):
    with pytest.raises(launch.LaunchError, match=r"unrendered placeholders: .*car.*--var"):
        launch.compose(role, config, f"carhunt-{role}")


def test_parse_vars():
    assert launch.parse_vars(["country=DE", "agent.x=1"]) == {"country": "DE", "country_lc": "de", "agent.x": "1"}
    assert launch.parse_vars(["country=DE", "country_lc=deu"])["country_lc"] == "deu"
    for bad in ("novalue", "Car=1", "=x"):
        with pytest.raises(launch.LaunchError, match="key=value"):
            launch.parse_vars([bad])


def test_variant_role_uses_base_brief(home, config, dummy_role):
    brief, variant = launch.resolve_role("dummy-abroad")
    assert brief.parent.name == "dummy" and variant == "abroad"
    assert launch.resolve_role("dummy") == (brief, None)
    with pytest.raises(launch.LaunchError, match="no brief"):
        launch.resolve_role("nosuch-home")


def test_list_of_mappings_renders():
    assert launch.flatten({"m": [{"make": "A", "tier": 1}, {"make": "B", "tier": 2}]}) == {"m": "make=A tier=1; make=B tier=2"}


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
