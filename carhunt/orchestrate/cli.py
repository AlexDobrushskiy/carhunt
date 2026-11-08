"""CLI groups: agent state msg pause unpause digest learn schedule hooks.

Each subcommand sets `func(args) -> int` (exit code) via set_defaults.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from carhunt.core import clock

from . import settings


def _backend():
    from .session import backend
    return backend(settings.load())


def _print(obj) -> None:
    print(obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False))


def _fail(e: Exception) -> int:
    print(f"carhunt: {e}", file=sys.stderr)
    return 1


# -- agent

def cmd_agent_launch(a) -> int:
    from . import launch
    extra = launch.parse_vars(a.var)
    sid = launch.launch(a.role, successor_of=a.successor_of, name=a.name, backend=_backend(),
                        force=a.force, extra=extra)
    _print({"role": a.role, "session": sid})
    return 0


def cmd_agent_side(a) -> int:
    from . import launch
    text = sys.stdin.read() if a.task_file == "-" else Path(a.task_file).read_text()
    _print({"session": launch.side_task(a.name, text, backend=_backend())})
    return 0


def _resolve(target: str | None) -> tuple[str, str]:
    from . import msg
    if not target:
        sid = settings.self_session_id()
        if not sid:
            raise RuntimeError("no target and own session id unknown")
        return (settings.self_role() or "self"), sid
    return target, msg.resolve(target)


def cmd_agent_ls(a) -> int:
    from . import state
    be = _backend()
    rows = []
    for role in state.roles():
        d = state.read(role)
        sid = d.get("active_agent")
        alive = bool(sid) and be.alive(sid)
        rows.append({"role": role, "status": d.get("status"), "session": sid, "alive": alive,
                     "ctx": be.ctx_percent(sid) if alive else None, "summary": d.get("summary", "")})
    if a.json:
        _print(rows)
    else:
        for r in rows:
            ctx = f"ctx:{r['ctx']}%" if r["ctx"] is not None else "-"
            print(f"{r['role']:<16} {r['status']:<10} {'live' if r['alive'] else 'gone':<5} {ctx:<9} "
                  f"{r['session'] or '-'}  {r['summary']}")
    return 0


def cmd_agent_screen(a) -> int:
    _, sid = _resolve(a.target)
    print(_backend().screen(sid, a.lines), end="")
    return 0


def cmd_agent_ctx(a) -> int:
    _, sid = _resolve(a.target)
    pct = _backend().ctx_percent(sid)
    if pct is None:
        print("unknown (statusline not printing ctx:N%? run `carhunt doctor`)", file=sys.stderr)
        return 1
    over = pct >= int(settings.get(settings.load(), "orchestrate.handover_ctx_pct", 50))
    print(f"{pct}{'  (hand over now)' if over else ''}")
    return 0


def cmd_agent_close(a) -> int:
    _, sid = _resolve(a.target)
    _backend().close(sid)
    return 0


# -- state

def _role(a) -> str:
    role = getattr(a, "role", None) or settings.self_role()
    if not role:
        raise RuntimeError("--role needed outside an agent session (CARHUNT_AGENT unset)")
    return role


def cmd_state_get(a) -> int:
    from . import state
    _print(state.get_key(state.read(_role(a)), a.key))
    return 0


def cmd_state_set(a) -> int:
    from . import state
    state.set_key(_role(a), a.key, a.value)
    return 0


def cmd_state_add(a) -> int:
    from . import state
    state.add_key(_role(a), a.key, a.value)
    return 0


def cmd_state_done(a) -> int:
    from . import state
    state.done(_role(a), a.summary)
    return 0


def cmd_state_handover(a) -> int:
    from . import state
    text = sys.stdin.read() if a.notes_file == "-" else Path(a.notes_file).read_text()
    sid = state.handover(_role(a), state.load_notes(text), me=settings.self_session_id(), backend=_backend())
    _print({"successor": sid, "next": "stop now; the successor closes this session after `state takeover`"})
    return 0


def cmd_state_takeover(a) -> int:
    from . import state
    closed = state.takeover(_role(a), me=settings.self_session_id(), backend=_backend())
    _print({"active_agent": settings.self_session_id(), "closed_predecessor": closed})
    return 0


def cmd_state_cleanup(a) -> int:
    from . import state
    _print({"closed": state.cleanup(_backend())})
    return 0


def cmd_state_validate(a) -> int:
    from . import state
    bad = 0
    for role in state.roles():
        try:
            state.validate(state.read(role))
        except state.StateError as e:
            bad += 1
            print(f"{role}: {e}")
    return 1 if bad else 0


# -- msg / pause

def cmd_msg(a) -> int:
    from . import msg
    text = sys.stdin.read() if a.stdin else (a.text or "")
    _print(msg.send(a.to, text, backend=_backend(), interrupt=a.interrupt))
    return 0


def cmd_pause(a) -> int:
    from . import learn, pause
    if a.night:
        _print({"paused": True, "asked_for_lessons": learn.night(_backend())})
    else:
        _print(pause.pause(a.reason or ""))
    return 0


def cmd_unpause(a) -> int:
    from . import learn, pause
    if a.morning:
        _print({"unpaused": True, "told": learn.morning(_backend())})
    else:
        _print({"unpaused": pause.unpause()})
    return 0


# -- digest / learn

def cmd_digest(a) -> int:
    from . import digest
    slot = a.slot or ("morning" if clock.now().hour < 14 else "evening")
    backend = None
    try:
        backend = _backend()
    except Exception:  # noqa: BLE001 - digest still goes out without session info
        pass
    text = digest.send(slot, backend=backend, dry_run=a.dry_run)
    if a.dry_run:
        print(text)
    return 0


def cmd_learn_start(a) -> int:
    from . import learn
    _print({"session": learn.start(_backend())})
    return 0


def cmd_learn_collect(a) -> int:
    from . import learn
    _print(learn.collect(a.date))
    return 0


# -- schedule

def cmd_schedule(a) -> int:
    from . import schedule
    cfg = settings.load()
    if a.action == "show":
        print("\n".join(schedule.show(cfg)))
    elif a.action == "install":
        for p in schedule.install(cfg, load=not a.no_load):
            print(p)
    else:
        for p in schedule.uninstall():
            print(f"removed {p}")
    return 0


# -- hooks

def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


def cmd_hooks(a) -> int:
    from . import hooks
    path = Path(a.settings).expanduser() if a.settings else hooks.settings_path()
    if a.action == "show":
        status, cmd = hooks.statusline_status(path)
        cur = hooks.load(path).get("hooks", {})
        ours = [f"{ev}: {h['command'].split()[2]}" for ev, h in hooks._all_commands(cur)
                if hooks.MARKER in str(h.get("command", ""))]
        print("\n".join(ours) or "no carhunt hooks installed")
        print(f"statusLine: {status}")
        return 0
    if a.action == "statusline":
        status, _ = hooks.statusline_status(path)
        if status != "none":
            print(f"statusLine already set ({status}). Make it print ctx:N% and add the two "
                  "'carhunt ctx' lines from hooks/statusline.sh (see docs/orchestrate.md).")
            return 0
        cur = hooks.load(path)
        new = {**cur, "statusLine": hooks.statusline_entry()}
        print(f"will set statusLine in {path} to {new['statusLine']['command']}")
        if a.dry_run or not (a.yes or _confirm("apply?")):
            return 0
        hooks.write(path, new)
        return 0
    cur, new, diff = hooks.plan(path, remove=a.action == "uninstall")
    if not diff:
        print("hooks already up to date")
        return 0
    print(diff)
    if a.dry_run:
        return 0
    if not (a.yes or _confirm(f"apply to {path}?")):
        print("not applied")
        return 1
    if a.action == "install":
        hooks.write_guards(settings.load())
    backup = hooks.write(path, new)
    print(f"written {path}" + (f" (backup {backup.name})" if backup else ""))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    def wrap(fn):
        def run(a):
            try:
                return fn(a)
            except Exception as e:  # noqa: BLE001 - one-line error, non-zero exit
                return _fail(e)
        return run

    ag = subparsers.add_parser("agent", help="launch and inspect agent sessions").add_subparsers(
        dest="agent_cmd", required=True)
    p = ag.add_parser("launch", help="render a role brief and start its session")
    p.add_argument("role")
    p.add_argument("--successor-of")
    p.add_argument("--name")
    p.add_argument("--force", action="store_true", help="relaunch even if state says running")
    p.add_argument("--var", action="append", metavar="KEY=VALUE",
                   help="per-launch brief value, repeatable (vet/buy: car, vin, country, destination, …)")
    p.set_defaults(func=wrap(cmd_agent_launch))
    p = ag.add_parser("side", help="start a one-off side-task session")
    p.add_argument("name")
    p.add_argument("--task-file", required=True, help="Do/Done/Avoid text, or - for stdin")
    p.set_defaults(func=wrap(cmd_agent_side))
    p = ag.add_parser("ls", help="roles, sessions, status, ctx")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=wrap(cmd_agent_ls))
    for name, fn in (("screen", cmd_agent_screen), ("ctx", cmd_agent_ctx), ("close", cmd_agent_close)):
        p = ag.add_parser(name)
        p.add_argument("target", nargs="?", help="role or session id (default: own session)")
        if name == "screen":
            p.add_argument("--lines", type=int, default=40)
        p.set_defaults(func=wrap(fn))

    st = subparsers.add_parser("state", help="agent state.json + handover").add_subparsers(
        dest="state_cmd", required=True)
    for name, fn, args in (("get", cmd_state_get, ["key?"]), ("set", cmd_state_set, ["key", "value"]),
                           ("add", cmd_state_add, ["key", "value"]), ("done", cmd_state_done, []),
                           ("takeover", cmd_state_takeover, []), ("cleanup", cmd_state_cleanup, []),
                           ("validate", cmd_state_validate, [])):
        p = st.add_parser(name)
        for arg in args:
            p.add_argument(arg.rstrip("?"), nargs="?" if arg.endswith("?") else None)
        if name not in ("cleanup", "validate"):
            p.add_argument("--role", help="default: $CARHUNT_AGENT")
        if name == "done":
            p.add_argument("--summary")
        p.set_defaults(func=wrap(fn))
    p = st.add_parser("handover", help="write handover notes and spawn the successor")
    p.add_argument("--notes-file", required=True, help="JSON/YAML with handover_notes keys, or -")
    p.add_argument("--role")
    p.set_defaults(func=wrap(cmd_state_handover))

    p = subparsers.add_parser("msg", help="message an agent (mailbox; typing fallback)")
    p.add_argument("--to", required=True, help="role or session id")
    p.add_argument("text", nargs="?")
    p.add_argument("--stdin", action="store_true")
    p.add_argument("--interrupt", action="store_true", help="Esc first, then type (stop an irreversible step)")
    p.set_defaults(func=wrap(cmd_msg))

    p = subparsers.add_parser("pause", help="create PAUSE: every sender refuses")
    p.add_argument("--reason")
    p.add_argument("--night", action="store_true", help="also ask live agents for lessons (schedule)")
    p.set_defaults(func=wrap(cmd_pause))
    p = subparsers.add_parser("unpause", help="remove PAUSE (owner or schedule only)")
    p.add_argument("--morning", action="store_true", help="also tell agents what learning changed")
    p.set_defaults(func=wrap(cmd_unpause))

    p = subparsers.add_parser("digest", help="build and push the owner digest")
    p.add_argument("--slot", choices=["morning", "evening"])
    p.add_argument("--dry-run", action="store_true", help="print, don't send or consume inputs")
    p.set_defaults(func=wrap(cmd_digest))

    lg = subparsers.add_parser("learn", help="nightly learning loop").add_subparsers(dest="learn_cmd", required=True)
    lg.add_parser("start", help="launch the learning session").set_defaults(func=wrap(cmd_learn_start))
    p = lg.add_parser("collect", help="paths of the day's lessons/logs/digest inputs")
    p.add_argument("--date")
    p.set_defaults(func=wrap(cmd_learn_collect))

    p = subparsers.add_parser("schedule", help="launchd jobs from orchestrate.schedule")
    p.add_argument("action", choices=["install", "uninstall", "show"])
    p.add_argument("--no-load", action="store_true", help="write plists without launchctl bootstrap")
    p.set_defaults(func=wrap(cmd_schedule))

    p = subparsers.add_parser("hooks", help="Claude Code guard hooks + statusline")
    p.add_argument("action", choices=["install", "uninstall", "show", "statusline"])
    p.add_argument("--settings", help="settings.json (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    p.add_argument("--dry-run", action="store_true", help="show the diff only")
    p.add_argument("--yes", action="store_true", help="apply without asking")
    p.set_defaults(func=wrap(cmd_hooks))
