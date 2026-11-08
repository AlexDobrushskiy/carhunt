"""`carhunt hooks install|uninstall|show|statusline`: merge carhunt guards into Claude Code settings.

Target: `$CARHUNT_HOME/claude/settings.json`, which `carhunt agent launch` passes to every claude
agent with `--settings`. Why: the guards deny wacli sends and Keychain reads, which the owner's own
sessions may need; scoped this way they bind only carhunt agents. `--user` targets the user settings.

Merge rules: ours = entries naming carhunt_hook.py, plus the identity lease block from
`carhunt browser mcp-config --hooks` (matcher on carhunt's own identity MCP names). Foreign entries
are never changed or removed; where a foreign hook (in the target or the user settings, both load
in an agent) already runs an asyncRewake mailbox receiver, ours is left out so the two don't race.
Only the `hooks` section is diffed or printed — settings files can hold tokens in `env`.
"""
from __future__ import annotations

import copy
import difflib
import json
import os
import shlex
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from carhunt.core import paths

from . import settings

MARKER = "carhunt_hook.py"
FILE_TOOLS = "Read|Edit|Write|MultiEdit|NotebookEdit|Grep|Glob"
LEASE = "pw-identity hook"


class HooksError(RuntimeError):
    pass


def settings_path() -> Path:
    """Agent-scoped settings (`claude --settings`); never the user's own config."""
    return paths.home() / "claude" / "settings.json"


def user_settings_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"
    return Path(base).expanduser() / "settings.json"


def identity_hooks() -> dict[str, list]:
    """The browsers module's identity lease block (absolute pw-identity path, carhunt's MCP names)."""
    from carhunt.access import mcp
    return mcp.render_hooks(repo=paths.repo_root())["hooks"]


def identity_matcher() -> str:
    from carhunt.access import mcp
    return mcp.identity_tool_matcher()


def _ours(group: Mapping, hook: Mapping, matcher: str | None) -> bool:
    cmd = str(hook.get("command", ""))
    return MARKER in cmd or (matcher is not None and group.get("matcher") == matcher and LEASE in cmd)


def hook_script() -> Path:
    return paths.repo_root() / "hooks" / MARKER


def _cmd(name: str, python: str, home: Path) -> str:
    return f"{shlex.quote(python)} {shlex.quote(str(hook_script()))} {name} --home {shlex.quote(str(home))}"


def _all_commands(hooks: Mapping) -> list[tuple[str, dict]]:
    out = []
    for event, groups in hooks.items():
        for g in groups or []:
            for h in g.get("hooks") or []:
                out.append((event, h))
    return out


def _foreign_has(hooks: Mapping, event: str, needle: str, async_rewake: bool | None = None) -> bool:
    for ev, h in _all_commands(hooks):
        cmd = str(h.get("command", ""))
        if ev == event and needle in cmd and MARKER not in cmd:
            if async_rewake is None or bool(h.get("asyncRewake")) == async_rewake:
                return True
    return False


def desired(current: Mapping, *, python: str | None = None, home: Path | None = None,
            also: Mapping | None = None) -> dict[str, list]:
    """Our entries per event, minus the ones a foreign hook already covers.

    also: hooks of other settings that load in the same session (the user settings).
    """
    py = python or sys.executable
    hm = home or paths.home()
    want: dict[str, list] = {"PreToolUse": [
        {"matcher": f"Bash|Monitor|{FILE_TOOLS}",
         "hooks": [{"type": "command", "command": _cmd("secret-guard", py, hm), "timeout": 10}]},
        {"matcher": "Bash|Monitor",
         "hooks": [{"type": "command", "command": _cmd("send-guard", py, hm), "timeout": 10}]},
    ]}
    for event, groups in identity_hooks().items():
        want.setdefault(event, []).extend(groups)
    if not any(_foreign_has(h, "Stop", "", async_rewake=True) for h in (current, also or {})):
        for ev in ("SessionStart", "UserPromptSubmit", "Stop"):
            want[ev] = [{"hooks": [{"type": "command", "command": _cmd("mailbox", py, hm),
                                    "asyncRewake": True, "timeout": 2_000_000}]}]
    return want


def describe(hooks: Mapping) -> list[str]:
    """One line per carhunt entry: `event: guard`."""
    m = identity_matcher()
    out = []
    for event, groups in hooks.items():
        for g in groups or []:
            for h in g.get("hooks") or []:
                if _ours(g, h, m):
                    cmd = str(h.get("command", ""))
                    what = cmd.split()[2] if MARKER in cmd else f"identity lease ({cmd.split()[-1]})"
                    out.append(f"{event}: {what}")
    return out


def strip_ours(hooks: Mapping, matcher: str | None = None) -> dict:
    out: dict = {}
    for event, groups in hooks.items():
        kept = []
        for g in groups or []:
            hs = [h for h in g.get("hooks") or [] if not _ours(g, h, matcher)]
            if hs:
                kept.append({**g, "hooks": hs})
            elif not g.get("hooks"):
                kept.append(g)
        if kept:
            out[event] = kept
    return out


def merge(settings: Mapping, want: Mapping[str, list] | None) -> dict:
    if not isinstance(settings, Mapping):
        raise HooksError("settings.json is not a JSON object; refusing to touch it")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, Mapping) or any(not isinstance(v, list) for v in hooks.values()):
        raise HooksError("settings.json `hooks` has an unexpected shape; refusing to touch it")
    new_hooks = strip_ours(hooks, identity_matcher())
    for event, groups in (want or {}).items():
        new_hooks.setdefault(event, [])
        new_hooks[event] = new_hooks[event] + copy.deepcopy(groups)
    out = dict(settings)
    if new_hooks:
        out["hooks"] = new_hooks
    else:
        out.pop("hooks", None)
    return out


def hooks_diff(old: Mapping, new: Mapping, label: str) -> str:
    a = json.dumps({"hooks": old.get("hooks", {})}, indent=2).splitlines()
    b = json.dumps({"hooks": new.get("hooks", {})}, indent=2).splitlines()
    return "\n".join(difflib.unified_diff(a, b, f"{label} (hooks)", f"{label} (hooks, new)", lineterm=""))


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError as e:
        raise HooksError(f"{path} is not valid JSON ({e.msg} at line {e.lineno}); refusing to touch it") from e
    if not isinstance(data, dict):
        raise HooksError(f"{path} is not a JSON object; refusing to touch it")
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict) or any(not isinstance(v, list) or any(not isinstance(g, dict) for g in v)
                                          for v in hooks.values()):
        raise HooksError(f"{path}: `hooks` has an unexpected shape; refusing to touch it")
    return data


def write(path: Path, data: Mapping) -> Path | None:
    backup = None
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-carhunt-{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_bytes(path.read_bytes())
        os.chmod(backup, 0o600)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp-carhunt")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return backup


def write_guards(config: Mapping) -> Path:
    """Guard config the stdlib hook reads (no YAML parser there)."""
    p = paths.home() / "hooks" / "guards.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    g = settings.get(config, "orchestrate.hooks", {}) or {}
    p.write_text(json.dumps({"secret_globs": g.get("secret_globs") or [],
                             "send_patterns": g.get("send_patterns") or []}, indent=2) + "\n")
    return p


def plan(path: Path, *, remove: bool = False, python: str | None = None) -> tuple[dict, dict, str]:
    cur = load(path)
    user = user_settings_path()
    also = {}
    if user.resolve() != path.resolve():
        try:
            also = load(user).get("hooks", {})
        except HooksError:
            also = {}
    new = merge(cur, None if remove else desired(cur.get("hooks", {}), python=python, also=also))
    return cur, new, hooks_diff(cur, new, str(path))


def statusline_status(path: Path) -> tuple[str, str]:
    """('ours'|'foreign'|'none', command)."""
    sl = load(path).get("statusLine") or {}
    cmd = str(sl.get("command", "")) if isinstance(sl, Mapping) else ""
    if not cmd:
        return "none", ""
    return ("ours" if "hooks/statusline.sh" in cmd else "foreign"), cmd


def statusline_entry() -> dict:
    return {"type": "command", "command": shlex.quote(str(paths.repo_root() / "hooks" / "statusline.sh"))}


def probe_statusline(cmd: str, sid: str = "carhunt-doctor") -> bool:
    """Run a statusline command on a sample payload; True when it prints ctx:N%."""
    import subprocess
    sample = json.dumps({"context_window": {"used_percentage": 37}, "model": {"display_name": "probe"},
                         "workspace": {"current_dir": str(Path.home())}})
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CARHUNT_SESSION_ID", "AGTERM_SESSION_ID"))}
    try:
        res = subprocess.run(["/bin/sh", "-c", cmd], input=sample, capture_output=True, text=True,
                             timeout=10, env=env, check=False)
    except subprocess.TimeoutExpired:
        return False
    return "ctx:37%" in res.stdout
