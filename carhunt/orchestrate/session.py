"""Session backends: where agent processes run and how we talk to them.

Interface (design.md): spawn, send, screen, ctx_percent, close, alive. One backend today:
agterm (macOS terminal with a control socket and per-pane mailboxes). The interface is small
so a tmux backend can be added without touching callers.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from carhunt.core import paths

from . import settings

CTX_RE = re.compile(r"ctx:(\d{1,3})%")
UUID_RE = re.compile(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", re.I)
CTX_FRESH_S = 15 * 60


class SessionError(RuntimeError):
    pass


class Backend(Protocol):
    def spawn(self, name: str, cwd: str, cmd: list[str], env: Mapping[str, str],
              after: str | None = None) -> str: ...
    def send(self, sid: str, text: str, interrupt: bool = False) -> str: ...
    def screen(self, sid: str, lines: int = 40) -> str: ...
    def ctx_percent(self, sid: str) -> int | None: ...
    def close(self, sid: str) -> None: ...
    def alive(self, sid: str) -> bool: ...


def ctx_file(sid: str) -> Path:
    """Written by hooks/statusline.sh on every statusline render: {"pct": N, "ts": epoch}."""
    return paths.home() / "ctx" / f"{paths.safe_name(sid, 'session id')}.json"


def ctx_from_file(sid: str, max_age_s: int = CTX_FRESH_S) -> int | None:
    try:
        d = json.loads(ctx_file(sid).read_text())
        if time.time() - float(d.get("ts", 0)) <= max_age_s:
            return int(d["pct"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def ctx_from_screen(text: str) -> int | None:
    found = CTX_RE.findall(text or "")
    return int(found[-1]) if found else None


def mailbox_marker(sid: str) -> Path:
    """Written by the carhunt mailbox receiver hook while a Claude Code listens in that session."""
    return paths.home() / "mailbox" / f"{paths.safe_name(sid, 'session id')}.json"


def pid_alive(pid: object) -> bool:
    try:
        os.kill(int(pid), 0)  # type: ignore[arg-type]
        return True
    except (OSError, TypeError, ValueError):
        return False


Runner = Callable[..., subprocess.CompletedProcess]


def _run(args: list[str], stdin: str | None = None, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout, check=False)


class AgtermBackend:
    """agtermctl wrapper. Every call names its target session explicitly.

    Lesson (EV run, 11-01): an agtermctl call without --target hits whatever session the
    user has selected — rename/type landed in the wrong session twice.
    """

    def __init__(self, ctl: str | None = None, runner: Runner = _run, mailbox: str = "carhunt",
                 workspace: str = "", shell: str | None = None) -> None:
        self.ctl = ctl or os.environ.get("AGTERMCTL") or shutil.which("agtermctl") or "agtermctl"
        self.runner = runner
        self.mailbox = mailbox
        self.workspace = workspace
        self.shell = shell or os.environ.get("SHELL") or "/bin/zsh"

    # -- plumbing
    def _ctl(self, *args: str, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
        res = self.runner([self.ctl, *args], stdin=stdin)
        if check and res.returncode != 0:
            raise SessionError(f"agtermctl {' '.join(args[:2])}: {(res.stderr or res.stdout).strip()}")
        return res

    def _json(self, *args: str) -> dict:
        res = self._ctl(*args, "--json")
        try:
            return json.loads(res.stdout or "{}")
        except json.JSONDecodeError as e:
            raise SessionError(f"agtermctl {' '.join(args[:2])}: bad json") from e

    def _sessions(self) -> list[dict]:
        out: list[dict] = []

        def walk(node: object) -> None:
            if isinstance(node, dict):
                if node.get("id") and "surfaces" in node:
                    out.append(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        windows = (self._json("window", "list").get("result") or {}).get("windows") or [{"id": None}]
        for w in windows:
            if w.get("id") is not None and w.get("open") is False:
                continue
            args = ["tree"] + (["--window", w["id"]] if w.get("id") else [])
            walk(self._json(*args).get("result"))
        return out

    def _node(self, sid: str) -> dict | None:
        for n in self._sessions():
            if n["id"].lower() == sid.lower():
                return n
        return None

    # -- interface
    def spawn(self, name: str, cwd: str, cmd: list[str], env: Mapping[str, str],
              after: str | None = None) -> str:
        exports = " ".join(f"export {k}={shlex.quote(v)};" for k, v in env.items())
        if env.get("CARHUNT_BIN_DIR"):  # the carhunt that launched us comes first on the agent's PATH
            exports += f' export PATH={shlex.quote(env["CARHUNT_BIN_DIR"])}:"$PATH";'
        # login shell so PATH matches the user's terminal; exec so the session ends with the agent
        script = f"{exports} cd {shlex.quote(cwd)} && exec {shlex.join(cmd)}"
        args = ["session", "new", "--cwd", cwd, "--name", name, "--no-select",
                "--command", f"{shlex.quote(self.shell)} -lc {shlex.quote(script)}"]
        if after:
            args += ["--after", after]
        elif self.workspace:
            args += ["--workspace-name", self.workspace, "--create-workspace"]
        data = self._json(*args)
        res = data.get("result") or {}
        sid = res.get("id") or (res.get("session") or {}).get("id")
        if not sid:
            m = UUID_RE.search(json.dumps(data))
            sid = m.group(0) if m else None
        if not sid:
            raise SessionError("agtermctl session new returned no session id")
        return sid

    def _has_receiver(self, sid: str) -> bool:
        if self.mailbox == "external":
            return True
        if self.mailbox != "carhunt":
            return False
        try:
            return pid_alive(json.loads(mailbox_marker(sid).read_text()).get("pid"))
        except (OSError, ValueError):
            return False

    def send(self, sid: str, text: str, interrupt: bool = False) -> str:
        """Mailbox when a receiver listens (arrives as a new turn when idle), else type + Return.

        interrupt: Esc first, then type — mail waits for the turn to end, which is too late to
        stop an irreversible step (EV run 11-02: a signup ran from the wrong IP while mail waited).
        """
        node = self._node(sid)
        if not node:
            raise SessionError(f"no open session {sid}")
        if interrupt:
            self._ctl("session", "type", "--target", node["id"], "\x1b")
            time.sleep(1.0)
            self._type(node["id"], text)
            return "type"
        if self._has_receiver(node["id"]):
            pane = next((s.get("paneID") for s in node.get("surfaces") or []
                         if s.get("kind") in ("left", "primary") and s.get("paneID")), None)
            if pane:
                res = self._ctl("msg", "send", "--stdin", "--to", f"{node['id']}:{pane}", "--json",
                                stdin=text.strip(), check=False)
                if res.returncode == 0:
                    return "mailbox"
        self._type(node["id"], text)
        return "type"

    def _type(self, sid: str, text: str) -> None:
        # one line, then Return as its own keystroke: a TUI takes a fast burst as a paste and can
        # swallow a Return sent with it (EV run 11-01: half a decision sat unsent in an input box)
        line = " ".join(text.split())
        self._ctl("session", "type", "--target", sid, "--stdin", stdin=line)
        time.sleep(1.5)
        tail = line[-40:].strip()
        for _ in range(3):
            self._ctl("session", "type", "--target", sid, "\r")
            time.sleep(1.5)
            box = self.screen(sid, 12).splitlines()[-8:]
            if not any(tail and tail in row for row in box if row.lstrip().startswith(("❯", "›", ">"))):
                return

    def screen(self, sid: str, lines: int = 40) -> str:
        return self._ctl("session", "text", "--target", sid, "--lines", str(lines)).stdout

    def ctx_percent(self, sid: str) -> int | None:
        pct = ctx_from_file(sid)
        if pct is not None:
            return pct
        try:
            return ctx_from_screen("\n".join(self.screen(sid, 8).splitlines()[-6:]))
        except SessionError:
            return None

    def close(self, sid: str) -> None:
        if self.alive(sid):
            self._ctl("session", "close", "--target", sid)

    def alive(self, sid: str) -> bool:
        try:
            return self._node(sid) is not None
        except SessionError:
            return False


def backend(config: Mapping | None = None) -> Backend:
    config = config if config is not None else settings.load()
    kind = settings.get(config, "orchestrate.session_backend", "agterm")
    if kind == "agterm":
        return AgtermBackend(mailbox=settings.get(config, "orchestrate.mailbox", "carhunt"),
                             workspace=settings.get(config, "orchestrate.workspace", "") or "")
    raise SessionError(f"unknown session backend {kind!r} (supported: agterm)")
