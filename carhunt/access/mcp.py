"""MCP server wiring: per-server ports for `browsers/bin/serve`, client registrations, Claude Code hooks, launchd jobs.

Server names carry a prefix (config `browsers.mcp_name_prefix`, default "ch-"): `ch-lane`, `ch-lane-a…`,
`ch-identity`, `ch-identity-a…`. Why: they must not clash with a pre-existing personal stack registered as
`identity` / `pw-lane-*` on other ports; the identity hooks match on these names.

  python -m carhunt.access.mcp ports <lanes|identity|identity-x>      shell vars for serve (MCP_PORT, …)
  python -m carhunt.access.mcp mcp-config [--claude|--json|--codex|--hooks] [--scope user]
  python -m carhunt.access.mcp launchd render [--out DIR] | install [--dry-run] | uninstall [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from carhunt.access import _core
from carhunt.access import settings as _settings

REPO = Path(__file__).resolve().parents[2]
BROWSERS = REPO / "browsers"
DEFAULT_PREFIX = "ch-"
LABEL_GUARD = "carhunt."           # we only ever write/load/kick launchd jobs with this prefix
_NAME_RE = re.compile(r"[A-Za-z0-9_-]*")


# ---------- names ----------

def name_prefix() -> str:
    p = str(_core.section("browsers").get("mcp_name_prefix", DEFAULT_PREFIX))
    if not _NAME_RE.fullmatch(p):
        raise ValueError(f"browsers.mcp_name_prefix {p!r}: only letters, digits, '-' and '_'")
    return p


def server_name(backend: str, prefix: str | None = None) -> str:
    """MCP registration name of an identity backend ("identity", "identity-a")."""
    return f"{name_prefix() if prefix is None else prefix}{backend}"


def browser_for_server(name: str, prefix: str | None = None) -> str | None:
    """Identity backend behind an MCP server name (`ch-identity-b` → `identity-b`), else None."""
    p = name_prefix() if prefix is None else prefix
    if not name.startswith(p):
        return None
    rest = name[len(p):]
    return rest if re.fullmatch(r"identity(-[a-h])?", rest) else None


def identity_tool_matcher(prefix: str | None = None) -> str:
    """Claude Code hook matcher (regex) for every identity tool call."""
    return f"mcp__{name_prefix() if prefix is None else prefix}identity(-[a-h])?__.*"


@dataclass(frozen=True)
class Registration:
    name: str       # MCP server name the agent sees (tools: mcp__<name>__browser_*)
    backend: str    # serve mode: lanes | identity | identity-<x>
    port: int

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}/mcp"   # the server rejects Host: 127.0.0.1 (rebinding guard)


def registrations(s: _settings.Settings | None = None) -> list[Registration]:
    """Lanes: one --isolated server, several names (one per subagent: each connection = its own context).
    Identity: the master + one server per pool copy."""
    s = s or _settings.load()
    p = name_prefix()
    lane_port = s.mcp_port("lanes")
    regs = [Registration(f"{p}lane", "lanes", lane_port)]
    regs += [Registration(f"{p}lane-{c}", "lanes", lane_port) for c in _settings.POOL_LETTERS[: s.lanes]]
    regs.append(Registration(f"{p}identity", "identity", s.mcp_port("identity")))
    regs += [Registration(f"{p}{b}", b, s.mcp_port(b)) for b in s.pool_names()]
    return regs


def backends(s: _settings.Settings | None = None) -> list[str]:
    s = s or _settings.load()
    return ["lanes", "identity", *s.pool_names()]


# ---------- serve helper ----------

def ports(mode: str, s: _settings.Settings | None = None) -> dict[str, str]:
    """Everything `serve <mode>` needs; writes the Playwright MCP config (debug port) it points at.
    Env CARHUNT_MCP_PORT / _DEBUG_PORT / _PROFILE / _OUT override (one-off runs, tests)."""
    s = s or _settings.load()
    if mode not in backends(s):
        raise ValueError(f"unknown mode {mode!r}: {', '.join(backends(s))}")
    env = os.environ
    mcp_port = int(env.get("CARHUNT_MCP_PORT") or s.mcp_port(mode))
    debug_port = int(env.get("CARHUNT_MCP_DEBUG_PORT") or s.debug_port(mode))
    isolated = mode == "lanes"
    profile = "" if isolated else str(Path(env.get("CARHUNT_MCP_PROFILE") or s.profile_dir(mode)))
    out = Path(env.get("CARHUNT_MCP_OUT") or s.mcp_out / mode)
    out.mkdir(parents=True, exist_ok=True)
    if profile:
        Path(profile).mkdir(parents=True, exist_ok=True)
    # The debug port lets the captcha solver attach to the tab an agent opened through MCP (10-27).
    cfg = {"browser": {"launchOptions": {"args": [f"--remote-debugging-port={debug_port}"]}}}
    cfg_path = s.dir("mcp-config") / f"{mode}.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    return {"MCP_PORT": str(mcp_port), "DEBUG_PORT": str(debug_port), "PROFILE": profile,
            "OUT_DIR": str(out), "CONFIG": str(cfg_path), "ISOLATED": "1" if isolated else "0",
            "HEADLESS": "1" if s.headless else "0"}


# ---------- client config ----------

def render_claude(regs: list[Registration], scope: str = "user") -> list[str]:
    return [f"claude mcp add --scope {scope} --transport http {r.name} {r.url}" for r in regs]


def render_json(regs: list[Registration], template: Path | None = None) -> dict:
    """`mcpServers` JSON from browsers/mcp.json.tmpl (one entry template, repeated per server)."""
    tmpl = json.loads((template or BROWSERS / "mcp.json.tmpl").read_text())
    (entry,) = tmpl["mcpServers"].values()
    raw = json.dumps(entry)
    return {"mcpServers": {r.name: json.loads(raw.replace("${port}", str(r.port)).replace("${name}", r.name))
                           for r in regs}}


def render_codex(regs: list[Registration]) -> str:
    """Codex ~/.codex/config.toml blocks. No identity lease there: hooks are Claude-Code-only."""
    return "\n".join(f'[mcp_servers.{json.dumps(r.name)}]\nurl = "{r.url}"\n' for r in regs)


def render_hooks(prefix: str | None = None, repo: Path = REPO,
                 template: Path | None = None) -> dict:
    """Claude Code settings `hooks` block: identity lease bookkeeping around every identity tool call."""
    data = json.loads((template or BROWSERS / "hooks" / "claude-settings-hooks.json").read_text())
    data.pop("_comment", None)
    want = identity_tool_matcher(prefix)
    for groups in data["hooks"].values():
        for g in groups:
            g["matcher"] = want
            for h in g.get("hooks", []):
                # the command runs through a shell: quote the path (a repo under "My Projects" must still work)
                exe, _, rest = h["command"].partition(" ")
                exe = shlex.quote(exe.replace("__REPO__", str(repo)))
                h["command"] = f"{exe} {rest}".rstrip()
    return data


# ---------- launchd ----------

def _xml_env(env: dict[str, str]) -> str:
    rows = "".join(f"\n    <key>{escape(k)}</key><string>{escape(v)}</string>" for k, v in env.items())
    return f"<dict>{rows}\n  </dict>"


@dataclass(frozen=True)
class Job:
    label: str
    template: str      # file in browsers/launchd/
    x: str = ""        # pool letter for identity-x.plist.tmpl


def jobs(s: _settings.Settings | None = None) -> list[Job]:
    s = s or _settings.load()
    if not s.launchd_prefix.startswith(LABEL_GUARD):
        raise ValueError(f"browsers.launchd_prefix {s.launchd_prefix!r} must start with {LABEL_GUARD!r}")
    out = [Job(s.label("lanes"), "lanes.plist.tmpl"), Job(s.label("identity"), "identity.plist.tmpl")]
    out += [Job(s.label(b), "identity-x.plist.tmpl", b.removeprefix("identity-")) for b in s.pool_names()]
    out += [Job(s.label("agent-chrome-refresh"), "agent-chrome-refresh.plist.tmpl"),
            Job(s.label("identity-seed"), "identity-seed.plist.tmpl"),
            Job(s.label("browser-reaper"), "browser-reaper.plist.tmpl")]
    return out


def render_plists(s: _settings.Settings | None = None, *, repo: Path = REPO, home: Path | None = None,
                  log_dir: Path | None = None, node: str | None = None, python: str | None = None
                  ) -> dict[str, str]:
    """{label: plist xml}. Paths resolved at render time: launchd runs with a bare PATH and no shell profile."""
    s = s or _settings.load()
    home = home or _core.home()
    log_dir = log_dir or s.logs
    node = node or os.environ.get("CARHUNT_NODE") or shutil.which("node") or "node"
    python = python or os.environ.get("CARHUNT_PYTHON") or str(repo / ".venv" / "bin" / "python")
    path_dirs = [str(Path(node).parent)] if os.sep in node else []
    path_dirs += ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    env = {"PATH": ":".join(dict.fromkeys(path_dirs)), "CARHUNT_HOME": str(home), "CARHUNT_NODE": node,
           "CARHUNT_PYTHON": python, "CARHUNT_LAUNCHD_PREFIX": s.launchd_prefix}
    if os.environ.get("CARHUNT_CONFIG"):
        env["CARHUNT_CONFIG"] = os.environ["CARHUNT_CONFIG"]
    if os.environ.get("CARHUNT_CHROME_APP"):
        env["CARHUNT_CHROME_APP"] = os.environ["CARHUNT_CHROME_APP"]
    if os.environ.get("CARHUNT_AGENT_CHROME_ID"):
        env["CARHUNT_AGENT_CHROME_ID"] = os.environ["CARHUNT_AGENT_CHROME_ID"]
    subs = {"__LABEL_PREFIX__": escape(s.launchd_prefix), "__REPO__": escape(str(repo)),
            "__CARHUNT_HOME__": escape(str(home)), "__LOG_DIR__": escape(str(log_dir)),
            "__ENV__": _xml_env(env)}
    out = {}
    for job in jobs(s):
        text = (BROWSERS / "launchd" / job.template).read_text()
        for k, v in {**subs, "__X__": job.x}.items():
            text = text.replace(k, v)
        if f"<string>{escape(job.label)}</string>" not in text:
            raise ValueError(f"{job.template}: rendered label is not {job.label}")
        out[job.label] = text
    return out


def _agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def install(*, dry_run: bool = True, agents_dir: Path | None = None,
            run: Callable[[list[str]], object] | None = None, out=sys.stdout, **render_kw) -> list[str]:
    """Write the plists and (re)load them. dry_run: print what would happen, touch nothing."""
    agents_dir = agents_dir or _agents_dir()
    run = run or (lambda cmd: subprocess.run(cmd, check=False))
    plists = render_plists(**render_kw)
    uid = os.getuid()
    actions = []
    for label, xml in plists.items():
        assert label.startswith(LABEL_GUARD), label
        dst = agents_dir / f"{label}.plist"
        cmds = [["launchctl", "bootout", f"gui/{uid}/{label}"], ["launchctl", "bootstrap", f"gui/{uid}", str(dst)]]
        actions.append(f"write {dst}")
        actions += [shlex.join(c) for c in cmds]
        if dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        Path(render_kw.get("log_dir") or _settings.load().logs).mkdir(parents=True, exist_ok=True)
        dst.write_text(xml)
        for c in cmds:
            run(c)
    for a in actions:
        print(("would: " if dry_run else "") + a, file=out)
    return actions


def uninstall(*, dry_run: bool = True, agents_dir: Path | None = None,
              run: Callable[[list[str]], object] | None = None, out=sys.stdout) -> list[str]:
    agents_dir = agents_dir or _agents_dir()
    run = run or (lambda cmd: subprocess.run(cmd, check=False))
    uid = os.getuid()
    actions = []
    for job in jobs():
        assert job.label.startswith(LABEL_GUARD), job.label
        dst = agents_dir / f"{job.label}.plist"
        cmd = ["launchctl", "bootout", f"gui/{uid}/{job.label}"]
        actions += [shlex.join(cmd), f"remove {dst}"]
        if not dry_run:
            run(cmd)
            dst.unlink(missing_ok=True)
    for a in actions:
        print(("would: " if dry_run else "") + a, file=out)
    return actions


# ---------- CLI ----------

def _cmd_ports(a) -> int:
    for k, v in ports(a.mode).items():
        print(f"{k}={shlex.quote(v)}")
    return 0


def _cmd_mcp_config(a) -> int:
    regs = registrations()
    if a.format == "json":
        print(json.dumps(render_json(regs), indent=2))
    elif a.format == "codex":
        print(render_codex(regs), end="")
    elif a.format == "hooks":
        print(json.dumps(render_hooks(), indent=2))
    else:
        print("\n".join(render_claude(regs, a.scope)))
    return 0


def _cmd_launchd(a) -> int:
    if a.action == "render":
        plists = render_plists()
        if a.out:
            d = Path(a.out)
            d.mkdir(parents=True, exist_ok=True)
            for label, xml in plists.items():
                (d / f"{label}.plist").write_text(xml)
                print(d / f"{label}.plist")
        else:
            for label, xml in plists.items():
                print(f"<!-- {label}.plist -->\n{xml}")
        return 0
    if a.action == "install":
        install(dry_run=a.dry_run)
    else:
        uninstall(dry_run=a.dry_run)
    return 0


def _add_mcp_config(sub) -> None:
    p = sub.add_parser("mcp-config", help="print MCP client registrations (claude mcp add lines by default)")
    g = p.add_mutually_exclusive_group()
    for fmt in ("claude", "json", "codex", "hooks"):
        g.add_argument(f"--{fmt}", dest="format", action="store_const", const=fmt)
    p.add_argument("--scope", default="user", help="claude mcp add --scope (default user)")
    p.set_defaults(format="claude", func=_cmd_mcp_config)


def _add_launchd(sub) -> None:
    p = sub.add_parser("launchd", help="render/install the carhunt.* launchd jobs (macOS)")
    p.add_argument("action", choices=["render", "install", "uninstall"])
    p.add_argument("--out", help="render: write <label>.plist files into this dir")
    p.add_argument("--dry-run", action="store_true", help="install/uninstall: print, change nothing")
    p.set_defaults(func=_cmd_launchd)


def register_cli(sub) -> None:
    """Add `mcp-config` and `launchd` to the `carhunt browser` subparsers; each sets func(args) -> int."""
    _add_mcp_config(sub)
    _add_launchd(sub)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m carhunt.access.mcp", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ports", help="shell variables for browsers/bin/serve")
    p.add_argument("mode")
    p.set_defaults(func=_cmd_ports)
    register_cli(sub)
    a = ap.parse_args(argv)
    try:
        return a.func(a)
    except ValueError as e:
        print(f"mcp: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
