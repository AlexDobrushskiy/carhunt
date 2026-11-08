"""MCP wiring: names, ports, client config, hooks, launchd plists (offline; launchctl faked)."""
from __future__ import annotations

import plistlib
import re

import pytest

from carhunt.access import mcp, settings

PERSONAL_PORTS = set(range(8931, 8937)) | set(range(9331, 9337))   # a pre-existing personal stack


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CARHUNT_HOME", str(tmp_path / "carhunt"))
    monkeypatch.delenv("CARHUNT_CONFIG", raising=False)
    for k in ("CARHUNT_MCP_PORT", "CARHUNT_MCP_DEBUG_PORT", "CARHUNT_MCP_PROFILE", "CARHUNT_MCP_OUT"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _config(tmp_path, monkeypatch, text):
    f = tmp_path / "config.yaml"
    f.write_text("owner: {tz: UTC}\n" + text)
    monkeypatch.setenv("CARHUNT_CONFIG", str(f))


def test_registration_names_and_ports():
    regs = mcp.registrations()
    names = [r.name for r in regs]
    assert names == ["ch-lane", "ch-lane-a", "ch-lane-b", "ch-lane-c", "ch-lane-d",
                     "ch-identity", "ch-identity-a", "ch-identity-b", "ch-identity-c", "ch-identity-d"]
    assert {r.port for r in regs if r.backend == "lanes"} == {18931}
    ident = {r.name: r.port for r in regs if r.backend != "lanes"}
    assert ident == {"ch-identity": 18932, "ch-identity-a": 18933, "ch-identity-b": 18934,
                     "ch-identity-c": 18935, "ch-identity-d": 18936}
    # never the user's own registrations
    assert not {"identity", "pw-lane", "pw-lane-a"} & set(names)


def test_no_port_collides_with_personal_stack_full_pool(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, "browsers:\n  identity_pool: 8\n  lanes: 8\n")
    s = settings.load()
    mcp_ports = [s.mcp_port(b) for b in mcp.backends(s)]
    debug_ports = [s.debug_port(b) for b in mcp.backends(s)] + [s.plain_debug_port]
    every = mcp_ports + debug_ports
    assert len(set(every)) == len(every), "ports collide among themselves"
    assert not set(every) & PERSONAL_PORTS


def test_ports_writes_debug_config_and_env_overrides(monkeypatch):
    v = mcp.ports("identity-b")
    assert v["MCP_PORT"] == "18934" and v["DEBUG_PORT"] == "19334" and v["ISOLATED"] == "0"
    assert v["PROFILE"].endswith("browsers/profiles/identity-b")
    cfg = open(v["CONFIG"]).read()
    assert "--remote-debugging-port=19334" in cfg
    lanes = mcp.ports("lanes")
    assert lanes["ISOLATED"] == "1" and lanes["PROFILE"] == ""
    monkeypatch.setenv("CARHUNT_MCP_PORT", "28000")
    monkeypatch.setenv("CARHUNT_MCP_DEBUG_PORT", "29000")
    v = mcp.ports("lanes")
    assert v["MCP_PORT"] == "28000" and "29000" in open(v["CONFIG"]).read()
    with pytest.raises(ValueError):
        mcp.ports("identity-z")


def test_ports_cli_is_shell_evaluable(capsys):
    assert mcp.main(["ports", "identity"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert all(re.fullmatch(r"[A-Z_]+=\S*", ln) for ln in lines), lines


def test_client_renders():
    regs = mcp.registrations()
    lines = mcp.render_claude(regs)
    assert lines[0] == "claude mcp add --scope user --transport http ch-lane http://localhost:18931/mcp"
    j = mcp.render_json(regs)["mcpServers"]
    assert j["ch-identity-c"] == {"type": "http", "url": "http://localhost:18935/mcp"}
    assert len(j) == len(regs)
    assert '[mcp_servers."ch-identity"]\nurl = "http://localhost:18932/mcp"' in mcp.render_codex(regs)


def test_hooks_matcher_and_server_mapping():
    h = mcp.render_hooks()
    assert set(h["hooks"]) == {"PreToolUse", "PostToolUse", "PostToolUseFailure"}
    m = re.compile(h["hooks"]["PreToolUse"][0]["matcher"])
    assert m.fullmatch("mcp__ch-identity__browser_navigate")
    assert m.fullmatch("mcp__ch-identity-d__browser_click")
    assert not m.fullmatch("mcp__identity__browser_click")       # the personal stack's server
    assert not m.fullmatch("mcp__ch-lane-a__browser_click")
    cmd = h["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    assert cmd.endswith("browsers/bin/pw-identity hook post") and "__REPO__" not in cmd
    assert mcp.browser_for_server("ch-identity-b") == "identity-b"
    assert mcp.browser_for_server("ch-identity") == "identity"
    assert mcp.browser_for_server("identity-b") is None
    assert mcp.browser_for_server("ch-lane-a") is None


def test_bad_name_prefix_refused(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, "browsers:\n  mcp_name_prefix: 'x y'\n")
    with pytest.raises(ValueError):
        mcp.registrations()


def test_plists_render_valid_and_labelled():
    plists = mcp.render_plists(node="/opt/node/bin/node", python="/opt/py/bin/python")
    assert set(plists) == {"carhunt.lanes", "carhunt.identity", "carhunt.identity-a", "carhunt.identity-b",
                           "carhunt.identity-c", "carhunt.identity-d", "carhunt.agent-chrome-refresh",
                           "carhunt.identity-seed", "carhunt.browser-reaper"}
    for label, xml in plists.items():
        assert label.startswith("carhunt.")
        assert "__" not in xml.replace("__pycache__", ""), f"unrendered placeholder in {label}"
        d = plistlib.loads(xml.encode())
        assert d["Label"] == label
        assert d["EnvironmentVariables"]["CARHUNT_NODE"] == "/opt/node/bin/node"
        assert d["EnvironmentVariables"]["PATH"].startswith("/opt/node/bin:")
    ia = plistlib.loads(plists["carhunt.identity-a"].encode())
    assert ia["ProgramArguments"][1:] == ["identity-a"] and ia["KeepAlive"] is True
    assert plistlib.loads(plists["carhunt.agent-chrome-refresh"].encode())["StartInterval"] == 21600
    assert plistlib.loads(plists["carhunt.identity-seed"].encode())["ProgramArguments"][1:] == ["seed", "--stale"]
    assert plistlib.loads(plists["carhunt.browser-reaper"].encode())["StartInterval"] == 1800


def test_prefix_outside_carhunt_refused(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, "browsers:\n  launchd_prefix: com.someone.\n")
    with pytest.raises(ValueError):
        mcp.render_plists()


def test_install_dry_run_touches_nothing(tmp_path):
    calls = []
    agents = tmp_path / "LaunchAgents"
    actions = mcp.install(dry_run=True, agents_dir=agents, run=calls.append, node="/n/node")
    assert not agents.exists() and calls == []
    assert any(a.startswith("launchctl bootstrap") for a in actions)


def test_install_and_uninstall_only_carhunt_labels(tmp_path):
    calls = []
    agents = tmp_path / "LaunchAgents"
    mcp.install(dry_run=False, agents_dir=agents, run=calls.append, node="/n/node")
    assert sorted(p.name for p in agents.iterdir())[0] == "carhunt.agent-chrome-refresh.plist"
    assert len(list(agents.iterdir())) == 9
    for c in calls:
        assert c[0] == "launchctl" and ("/carhunt." in c[2] or c[3].split("/")[-1].startswith("carhunt."))
    calls.clear()
    mcp.uninstall(dry_run=False, agents_dir=agents, run=calls.append)
    assert not list(agents.iterdir())
    assert all(c[1] == "bootout" and "/carhunt." in c[2] for c in calls)
