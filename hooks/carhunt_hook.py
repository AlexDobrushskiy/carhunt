#!/usr/bin/env python3
"""carhunt Claude Code hooks (stdlib only, so they start fast in any session).

  secret-guard    PreToolUse: deny reading secrets (files, Keychain, 1Password, env) and
                  `carhunt secret exec` into a printing command.
  send-guard      PreToolUse: deny direct seller sends (wacli writes, mailers, raw Telegram
                  Bot API, contact channel modules) -> use `carhunt say` / `carhunt notify`.
  identity-pre    PreToolUse on identity browser tools: lease check via `pw-identity hook pre`.
  identity-post   PostToolUse on identity browser tools: `pw-identity hook post`.
  mailbox         asyncRewake receiver: delivers agterm mailbox mail to an idle carhunt agent.

Guard config: <home>/hooks/guards.json (written by `carhunt hooks install`).
Why the secret guard exists: EV run 11-06, a "masked" credential dump missed a pattern and
~12 passwords landed in a transcript. Prose rules were not enough.
"""
from __future__ import annotations

import argparse
import fcntl
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

PRINTERS = {"env", "printenv", "echo", "printf", "set", "export", "declare", "cat", "tee", "xxd",
            "base64", "od", "hexdump", "strings", "less", "more", "head", "tail"}
SHELLS = {"sh", "bash", "zsh", "dash", "fish"}
INLINE = {"python", "python3", "node", "ruby", "perl"}
WACLI_WRITES = {"send", "reply", "react", "delete", "edit", "forward", "revoke"}
MAILERS = {"sendmail", "msmtp", "swaks", "mutt", "mailx"}
SEP = {";", "&&", "||", "|", "&", "|&", "\n", "(", ")"}


def load_guards(home: Path) -> dict:
    try:
        return json.loads((home / "hooks" / "guards.json").read_text())
    except (OSError, ValueError):
        return {}


def secret_globs(home: Path, guards: dict) -> list[str]:
    globs = guards.get("secret_globs") or ["{home}/secrets/**", "**/.env", "**/*.secret"]
    return [g.replace("{home}", str(home)) for g in globs]


# -- path matching

def _expand(tok: str, home: Path, cwd: str) -> str:
    t = tok.replace("${CARHUNT_HOME}", str(home)).replace("$CARHUNT_HOME", str(home))
    t = t.replace("${HOME}", os.path.expanduser("~")).replace("$HOME", os.path.expanduser("~"))
    t = os.path.expanduser(t)
    if not os.path.isabs(t):
        t = os.path.join(cwd or os.getcwd(), t)
    return os.path.normpath(t)


def is_secret_path(path: str, globs: list[str]) -> bool:
    p = os.path.normpath(path)
    for g in globs:
        pat = g.replace("**/", "*").replace("/**", "/*")
        if fnmatch.fnmatch(p, pat):
            return True
        if g.endswith("/**") and p == os.path.normpath(g[:-3]):
            return True
        if not g.startswith("/") and fnmatch.fnmatch(p, "*/" + g.lstrip("*/")):
            return True
    return False


# -- shell parsing

def tokens(cmd: str) -> list[str] | None:
    try:
        lex = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return None


def segments(cmd: str, depth: int = 0) -> list[list[str]]:
    """Simple commands of a shell line, including bodies of `sh -c` and `eval` (one level deep)."""
    toks = tokens(cmd)
    if toks is None:
        return [cmd.split()]
    segs: list[list[str]] = [[]]
    for t in toks:
        if t in SEP or set(t) <= set(";&|()"):
            segs.append([])
        else:
            segs[-1].append(t)
    out = []
    for s in segs:
        while s and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", s[0]):  # VAR=x cmd
            s = s[1:]
        while s and s[0] in ("sudo", "command", "exec", "nohup", "time", "xargs"):
            s = s[1:]
        if not s:
            continue
        out.append(s)
        base = os.path.basename(s[0])
        if depth < 2 and base in SHELLS and "-c" in s[1:]:
            i = s.index("-c")
            if i + 1 < len(s):
                out += segments(s[i + 1], depth + 1)
        if depth < 2 and base == "eval":
            out += segments(" ".join(s[1:]), depth + 1)
    return out


def deny(reason: str) -> int:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


# -- guards

SECRET_MSG = ("carhunt secret-guard: secrets are never read or printed, not even masked (EV run 11-06: a "
              "masked dump leaked passwords into a transcript). Use `carhunt secret ls|check|set` or "
              "`carhunt secret exec NAME -- <tool>`.")


def check_secret(event: dict, home: Path, guards: dict) -> str | None:
    tool = event.get("tool_name", "")
    ti = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    globs = secret_globs(home, guards)
    if tool in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Grep", "Glob"):
        for key in ("file_path", "notebook_path", "path"):
            v = ti.get(key)
            if v and is_secret_path(_expand(v, home, cwd), globs):
                return SECRET_MSG
        pat = ti.get("pattern") if tool == "Glob" else None
        if pat and is_secret_path(_expand(pat, home, cwd), globs):
            return SECRET_MSG
        return None
    if tool not in ("Bash", "Monitor"):
        return None
    cmd = ti.get("command") or ""
    if "CARHUNT_SECRET_" in cmd:
        return SECRET_MSG
    for seg in segments(cmd):
        base = os.path.basename(seg[0])
        args = seg[1:]
        if base == "carhunt" and args[:1] == ["secret"]:
            if args[1:2] == ["exec"] and "--" in args:
                target = args[args.index("--") + 1:]
                if target and _prints(target):
                    return SECRET_MSG
            continue
        if base == "security" and args and args[0].startswith(("find-", "dump-keychain")) and \
                (args[0] == "dump-keychain" or "-w" in args or "-g" in args):
            return SECRET_MSG
        if base == "op" and (args[:1] == ["read"] or "--reveal" in args):
            return SECRET_MSG
        for a in args:
            if re.search(r"[/~$.]", a) and is_secret_path(_expand(a, home, cwd), globs):
                return SECRET_MSG
    return None


def _prints(argv: list[str]) -> bool:
    base = os.path.basename(argv[0])
    if base in PRINTERS:
        return True
    if base in SHELLS and "-c" in argv:
        body = argv[argv.index("-c") + 1] if argv.index("-c") + 1 < len(argv) else ""
        return any(_prints(s) for s in segments(body))
    if re.match(r"^(python3?|node|ruby|perl)$", base) and any(a in ("-c", "-e") for a in argv):
        return True
    return False


SEND_MSG = ("carhunt send-guard: seller messages go only through `carhunt say` (pause, quiet hours, caps, "
            "duplicate check, ledger, cardb log in one locked step).")


def check_send(event: dict, home: Path, guards: dict) -> str | None:
    if event.get("tool_name") not in ("Bash", "Monitor"):
        return None
    cmd = (event.get("tool_input") or {}).get("command") or ""
    if re.search(r"api\.telegram\.org/bot[^\s'\"]*/send", cmd):
        return ("carhunt send-guard: pushes go through `carhunt notify --kind ask|urgent` so replies route "
                "back to you; raw Bot API sends can't be answered (EV run 11-04).")
    if re.search(r"carhunt[./]contact[./]channels", cmd):
        return SEND_MSG + " Don't call channel adapters directly."
    for seg in segments(cmd):
        base = os.path.basename(seg[0])
        sub = [a for a in seg[1:] if not a.startswith("-")]
        if base == "wacli" and sub and sub[0] in WACLI_WRITES:
            return SEND_MSG + f" Use `carhunt say --channel whatsapp` instead of `wacli {sub[0]}`."
        if base == "wacli" and sub[:2] in (["messages", "send"], ["message", "send"]):
            return SEND_MSG
        if base in MAILERS or (base in ("mail", "mailx") and "-s" in seg):
            return SEND_MSG + " Use `carhunt say --channel email`."
    for rule in guards.get("send_patterns") or []:
        if re.search(rule.get("regex", r"(?!)"), cmd):
            return SEND_MSG + (f" {rule['use']}" if rule.get("use") else "")
    return None


def delegate_identity(phase: str, raw: str) -> int:
    """The browsers module owns leases; without pw-identity there is no identity browser to guard."""
    exe = shutil.which("pw-identity")
    if not exe:
        return 0
    res = subprocess.run([exe, "hook", phase], input=raw, capture_output=True, text=True, check=False)
    sys.stdout.write(res.stdout)
    sys.stderr.write(res.stderr)
    return res.returncode


# -- mailbox receiver

WAIT_ROUND = 30


def mailbox(event: dict, home: Path) -> int:
    """asyncRewake: exit 2 with the mail on stderr starts a turn; any other path exits 0.

    Mail is taken only between turns (UserPromptSubmit marks busy; Stop / SessionStart clear it).
    Only carhunt agent sessions listen, so a user's own sessions are untouched.
    """
    sid, pane = os.environ.get("AGTERM_SESSION_ID", ""), os.environ.get("AGTERM_PANE_ID", "")
    if not (sid and pane and os.environ.get("CARHUNT_AGENT")):
        return 0
    ctl = os.environ.get("AGTERMCTL") or shutil.which("agtermctl") or "agtermctl"
    d = home / "mailbox"
    d.mkdir(parents=True, exist_ok=True)
    parent = os.getppid()
    marker, busy, lockp = d / f"{sid}.json", d / f"{sid}.busy", d / f"{sid}.lock"
    marker.write_text(json.dumps({"pid": parent, "pane": pane}))
    name = event.get("hook_event_name", "")
    if name == "UserPromptSubmit":
        busy.touch()
        return 0
    if not (name == "SessionStart" and event.get("source") == "compact"):
        busy.unlink(missing_ok=True)
    with open(lockp, "a") as lock:
        deadline = time.monotonic() + WAIT_ROUND + 15
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    return 0
                time.sleep(1)
        while os.getppid() == parent:
            res = subprocess.run([ctl, "msg", "read", "--wait", "--timeout", str(WAIT_ROUND), "--json",
                                  "--as", f"{sid}:{pane}"], capture_output=True, text=True, check=False,
                                 timeout=WAIT_ROUND + 15)
            if res.returncode == 124:
                continue
            if res.returncode != 0:
                time.sleep(5)  # agterm restarting: keep listening while this Claude runs
                continue
            msgs = (json.loads(res.stdout or "{}").get("result") or {}).get("messages") or []
            if not msgs or os.getppid() != parent:
                continue
            while busy.exists() and os.getppid() == parent:
                time.sleep(1)
            sys.stderr.write("\n\n".join(f"[agterm mailbox] {m.get('body', '')}" for m in msgs) + "\n")
            sys.stderr.flush()
            subprocess.run([ctl, "msg", "ack", "--as", f"{sid}:{pane}", *[m["id"] for m in msgs]],
                           capture_output=True, text=True, check=False)
            busy.touch()
            return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="carhunt_hook.py")
    p.add_argument("hook", choices=["secret-guard", "send-guard", "identity-pre", "identity-post", "mailbox"])
    p.add_argument("--home", default=os.environ.get("CARHUNT_HOME") or "~/.carhunt")
    a = p.parse_args(argv)
    home = Path(os.environ.get("CARHUNT_HOME") or a.home).expanduser()
    raw = sys.stdin.read()
    try:
        event = json.loads(raw or "{}")
    except ValueError:
        event = {}
    if a.hook in ("identity-pre", "identity-post"):
        return delegate_identity("pre" if a.hook == "identity-pre" else "post", raw)
    if a.hook == "mailbox":
        try:
            return mailbox(event, home)
        except Exception:  # noqa: BLE001 - a receiver error must never wake or block Claude
            return 0
    guards = load_guards(home)
    check = check_secret if a.hook == "secret-guard" else check_send
    reason = check(event, home, guards)
    return deny(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
