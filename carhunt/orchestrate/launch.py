"""Render a role brief and start its agent session.

Rendered brief = agents/templates/common.md + role brief (+ the user's local learned rules),
written to $CARHUNT_HOME/agents/<role>/brief.md. The repo is never edited at run time.
"""
from __future__ import annotations

import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import _core
from .session import Backend

PLACEHOLDER = re.compile(r"(?<!\{)\{([a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)*)\}(?!\})")


class LaunchError(RuntimeError):
    pass


def flatten(d: Mapping, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, Mapping):
            out.update(flatten(v, key + "."))
        elif isinstance(v, (list, tuple)):
            if all(not isinstance(x, (Mapping, list)) for x in v):
                out[key] = ", ".join(str(x) for x in v)
        elif v is not None:
            out[key] = str(v)
    return out


def render(text: str, variables: Mapping[str, Any]) -> str:
    """Replace {dotted.key}; unknown keys fail loudly; {{x}} renders as a literal {x}."""
    missing = sorted({m for m in PLACEHOLDER.findall(text) if m not in variables})
    if missing:
        raise LaunchError(f"unrendered placeholders: {', '.join(missing)}")
    out = PLACEHOLDER.sub(lambda m: str(variables[m.group(1)]), text)
    return out.replace("{{", "{").replace("}}", "}")


def unrendered(text: str) -> list[str]:
    return PLACEHOLDER.findall(text)


def templates_dir() -> Path:
    return _core.repo_root() / "agents" / "templates"


def role_brief_path(role: str) -> Path:
    """User-local roles ($CARHUNT_HOME/roles/<role>/brief.md) win over the repo's."""
    _core.safe_name(role, "role")
    for p in (_core.home() / "roles" / role / "brief.md",
              _core.repo_root() / "agents" / "roles" / role / "brief.md"):
        if p.is_file():
            return p
    raise LaunchError(f"no brief for role {role!r} (agents/roles/{role}/brief.md)")


def variables(config: Mapping, role: str, name: str, extra: Mapping[str, str] | None = None) -> dict:
    adir = _core.agent_dir(role)
    v = flatten(config)
    v.update({
        "home": str(_core.home()),
        "date": _core.now(config).date().isoformat(),
        "learned.dir": str(_core.home() / "learned"),
        "agent.role": role,
        "agent.name": name,
        "agent.dir": str(adir),
        "agent.brief": str(adir / "brief.md"),
        "agent.state": str(adir / "state.json"),
    })
    v.update(extra or {})
    return v


def compose(role: str, config: Mapping, name: str, *, body_path: Path | None = None,
            extra: Mapping[str, str] | None = None) -> str:
    v = variables(config, role, name, extra)
    parts = [render((templates_dir() / "common.md").read_text(), v),
             render((body_path or role_brief_path(role)).read_text(), v)]
    learned = _core.home() / "learned"
    for f in (learned / "common.md", learned / f"{role}.md"):
        if f.is_file() and f.read_text().strip():
            # local rules written by the learning session; included verbatim
            parts.append(f"# Local learned rules ({f.name})\n\n{f.read_text().strip()}\n")
    return "\n\n".join(p.rstrip() + "\n" for p in parts)


def agent_command(config: Mapping, prompt: str) -> list[str]:
    cli = _core.cfg(config, "orchestrate.agent_cli", "claude")
    args = list((_core.cfg(config, "orchestrate.agent_args", {}) or {}).get(cli) or [])
    if cli == "claude":
        # prompt first: variadic flags like --allowedTools would swallow a trailing prompt
        return ["claude", prompt, *args]
    if cli == "codex":
        # codex filters the shell env by default; agents need AGTERM_*/CARHUNT_* for state + guards
        return ["codex", prompt, "-c", "shell_environment_policy.inherit=all", *args]
    raise LaunchError(f"unknown agent_cli {cli!r} (claude | codex)")


def launch(role: str, *, successor_of: str | None = None, name: str | None = None,
           backend: Backend, config: Mapping | None = None, body_path: Path | None = None,
           extra: Mapping[str, str] | None = None, force: bool = False) -> str:
    """Render, init state (fresh launch only), spawn. Returns the new session id."""
    from . import state

    config = config if config is not None else _core.load_config()
    adir = _core.agent_dir(role)
    name = name or f"carhunt-{role}"
    brief = adir / "brief.md"
    if successor_of:
        if not brief.is_file():
            raise LaunchError(f"successor needs the predecessor's brief at {brief}")
    else:
        if state.path(role).is_file() and not force:
            cur = state.read(role)
            sid = cur.get("active_agent")
            if cur.get("status") == "running" and sid and backend.alive(sid):
                raise LaunchError(f"{role} already runs in session {sid} (one session per role; "
                                  "hand over or close it first)")
        brief.write_text(compose(role, config, name, body_path=body_path, extra=extra))
        (adir / "lessons").mkdir(exist_ok=True)
    env = {
        "CARHUNT_HOME": str(_core.home()),
        "CARHUNT_AGENT": role,
        "CARDB_AUTHOR": role,
        "CARHUNT_REPO": str(_core.repo_root()),
    }
    exe = shutil.which("carhunt")
    if exe:
        env["CARHUNT_BIN_DIR"] = str(Path(exe).parent)
    for k in ("CARHUNT_CONFIG", "CARHUNT_DENYLIST"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    if successor_of:
        prompt = (f"Read and execute {brief}. You are the successor of session {successor_of} for role "
                  f"{role}: read {state.path(role)} handover_notes first and rebuild state from files "
                  "(not from the notes alone), then run `carhunt state takeover` to confirm; that closes "
                  "the predecessor.")
    else:
        prompt = f"Read and execute {brief}."
    cmd = agent_command(config, prompt)
    sid = backend.spawn(name, str(adir), cmd, env, after=successor_of)
    if not successor_of:
        state.init(role, active_agent=sid, name=name,
                   cli=_core.cfg(config, "orchestrate.agent_cli", "claude"), brief=str(brief))
    return sid


def side_task(name: str, task_text: str, *, backend: Backend, config: Mapping | None = None) -> str:
    """One-off side session from agents/templates/side-task.md; role = side-<name>."""
    role = f"side-{_core.safe_name(name, 'side task')}"
    return launch(role, backend=backend, config=config, name=f"carhunt-{role}",
                  body_path=templates_dir() / "side-task.md",
                  extra={"task.name": name, "task.body": task_text.strip()})
