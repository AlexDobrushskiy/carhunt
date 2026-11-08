import pytest

from carhunt.orchestrate import launch, state

from .conftest import read_state


def test_schema_accepts_and_rejects(home):
    state.validate({"role": "x", "active_agent": "A", "status": "running"})
    with pytest.raises(state.StateError, match="status"):
        state.validate({"role": "x", "active_agent": "A", "status": "done+closed 13:3x"})
    with pytest.raises(state.StateError):
        state.validate({"role": "x", "status": "running"})
    with pytest.raises(state.StateError, match="pending_owner"):
        state.validate({"role": "x", "active_agent": None, "status": "running", "pending_owner": [{"id": "1"}]})


def test_launch_inits_state_and_env(home, config, fake, dummy_role):
    sid = launch.launch("dummy", backend=fake, config=config)
    s = read_state(home, "dummy")
    assert s["active_agent"] == sid and s["status"] == "running" and s["cli"] == "claude"
    sess = fake.sessions[sid]
    assert sess["env"]["CARDB_AUTHOR"] == "dummy" and sess["env"]["CARHUNT_HOME"] == str(home)
    assert sess["cmd"][0] == "claude" and not any(a.startswith("--dangerously") for a in sess["cmd"])
    assert sess["cmd"][1] == f"Read and execute {home / 'agents' / 'dummy' / 'brief.md'}."
    with pytest.raises(launch.LaunchError, match="already runs"):
        launch.launch("dummy", backend=fake, config=config)


def test_agent_args_opt_in(home, config, fake, dummy_role):
    config["orchestrate"]["agent_args"] = {"claude": ["--allowedTools", "Bash(carhunt state:*)"]}
    sid = launch.launch("dummy", backend=fake, config=config)
    assert fake.sessions[sid]["cmd"][2:4] == ["--allowedTools", "Bash(carhunt state:*)"]


def test_set_get_add(home, config, fake, dummy_role):
    launch.launch("dummy", backend=fake, config=config)
    state.set_key("dummy", "cursors.autoscout24", "2026-11-08T07:00")
    state.add_key("dummy", "open_issues", '{"id": "i1", "what": "blocked"}')
    state.add_key("dummy", "advice", "plain text stays a string")
    s = read_state(home, "dummy")
    assert s["cursors"] == {"autoscout24": "2026-11-08T07:00"}
    assert s["open_issues"][0]["id"] == "i1" and s["advice"] == ["plain text stays a string"]
    with pytest.raises(state.StateError):
        state.set_key("dummy", "active_agent", "X")
    with pytest.raises(state.StateError, match="invalid"):
        state.set_key("dummy", "status", "whatever")
    assert read_state(home, "dummy")["status"] == "running"  # invalid write not persisted


def test_handover_flow(home, config, fake, dummy_role):
    old = launch.launch("dummy", backend=fake, config=config)
    with pytest.raises(state.StateError, match="unanswered_inbound"):
        state.handover("dummy", {"open_threads": []}, me=old, backend=fake, config=config)
    with pytest.raises(state.StateError, match="not the active agent"):
        state.handover("dummy", {"unanswered_inbound": []}, me="SOMEONE-ELSE", backend=fake, config=config)
    notes = {"unanswered_inbound": [{"car": 12, "channel": "whatsapp", "at": "11:02"}], "pending_sends": []}
    new = state.handover("dummy", notes, me=old, backend=fake, config=config)
    s = read_state(home, "dummy")
    assert s["active_agent"] == old and s["handover_from"] == old and s["successor"]["id"] == new
    assert s["handover_notes"]["unanswered_inbound"][0]["car"] == 12
    assert fake.alive(old), "old session stays until the successor confirms"
    assert fake.sessions[new]["after"] == old
    assert f"successor of session {old}" in fake.sessions[new]["cmd"][1]
    with pytest.raises(state.StateError, match="successor"):
        state.takeover("dummy", me="INTRUDER", backend=fake)
    closed = state.takeover("dummy", me=new, backend=fake)
    s = read_state(home, "dummy")
    assert closed == old and not fake.alive(old)
    assert s["active_agent"] == new and s["handover_from"] is None and s["previous_agents"] == [old]


def test_cleanup_closes_completed_once(home, config, fake, dummy_role):
    sid = launch.launch("dummy", backend=fake, config=config)
    assert state.cleanup(fake) == []
    state.done("dummy", "finished")
    assert state.cleanup(fake) == [sid] and not fake.alive(sid)
    assert read_state(home, "dummy")["closed_at"]
    assert state.cleanup(fake) == []
    launch.launch("dummy", backend=fake, config=config)  # completed role can start again
    assert "closed_at" not in read_state(home, "dummy")


def test_contact_say_accepts_launched_agent_until_handover(home, config, fake, dummy_role, monkeypatch):
    """launch writes active_agent the way contact's `say` checks it (role dir + AGTERM_SESSION_ID)."""
    say = pytest.importorskip("carhunt.contact.say")
    s = {"require_active_agent": True}
    old = launch.launch("dummy-home", backend=fake, config=config)
    env = fake.sessions[old]["env"]
    assert env["CARHUNT_AGENT"] == env["CARDB_AUTHOR"] == "dummy-home"
    assert "AGTERM_SESSION_ID" not in env, "agterm sets the child's own id; never inherit the launcher's"
    for k in ("CARHUNT_AGENT", "CARDB_AUTHOR"):
        monkeypatch.setenv(k, env[k])
    monkeypatch.setenv("AGTERM_SESSION_ID", old)
    assert say.caller_problem(s) is None
    new = state.handover("dummy-home", {"unanswered_inbound": []}, me=old, backend=fake, config=config)
    state.takeover("dummy-home", me=new, backend=fake)
    assert "not the active dummy-home agent" in say.caller_problem(s)
    monkeypatch.setenv("AGTERM_SESSION_ID", new)
    assert say.caller_problem(s) is None
