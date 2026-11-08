"""core CLI groups: config, secret, notify, doctor."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

import yaml

from carhunt.core import config, doctor, notify, paths, secrets

EXIT_REFUSED, EXIT_FAILED = 10, 11


def _group(sub, name: str, help: str) -> tuple[argparse.ArgumentParser, argparse._SubParsersAction]:
    p = sub.add_parser(name, help=help, description=help)
    p.set_defaults(_parser=p)
    return p, p.add_subparsers(dest=f"{name}_cmd", metavar="<command>")


def _err(msg: str) -> None:
    print(f"carhunt: {msg}", file=sys.stderr)


def register(sub) -> None:
    _config(sub)
    _secret(sub)
    _notify(sub)
    p = sub.add_parser("doctor", help="check every component: ok / warn / fail with a fix line")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)


# --- config -----------------------------------------------------------------

def _config(sub) -> None:
    _, s = _group(sub, "config", "show / validate the config file")
    p = s.add_parser("show", help="print the config (secret refs as secret:NAME, never values)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_config_show)
    p = s.add_parser("get", help="print one value by dotted key (secret refs as secret:NAME); exit 1 if unset")
    p.add_argument("key", help="e.g. contact.quiet_hours")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_config_get)
    p = s.add_parser("validate", help="check a config file against the schema")
    p.add_argument("file", nargs="?")
    p.set_defaults(func=cmd_config_validate)
    p = s.add_parser("path", help="print the config file path")
    p.add_argument("--home", action="store_true", help="print $CARHUNT_HOME instead")
    p.set_defaults(func=cmd_config_path)


def cmd_config_show(a) -> int:
    try:
        data = config.load(check=False).as_dict()
    except config.ConfigError as e:
        _err(str(e))
        return 1
    print(json.dumps(data, indent=2, ensure_ascii=False) if a.json
          else yaml.safe_dump(data, sort_keys=False, allow_unicode=True), end="" if not a.json else "\n")
    return 0


def cmd_config_get(a) -> int:
    try:
        data = config.load(check=False).as_dict()
    except config.ConfigError as e:
        _err(str(e))
        return 1
    node = data
    for part in a.key.split("."):
        if not isinstance(node, dict) or part not in node:
            _err(f"{a.key} is not set")
            return 1
        node = node[part]
    if a.json or isinstance(node, (dict, list)):
        print(json.dumps(node, ensure_ascii=False))
    else:
        print("" if node is None else node)
    return 0


def cmd_config_validate(a) -> int:
    f = a.file or str(paths.config_file())
    try:
        errors = config.validate(config.read(Path(f).expanduser()))
    except config.ConfigError as e:
        _err(str(e))
        return 1
    if errors:
        print(f"{f}: invalid")
        for e in errors:
            print(f"  {e}")
        return 1
    print(f"{f}: ok")
    return 0


def cmd_config_path(a) -> int:
    print(paths.home() if a.home else paths.config_file())
    return 0


# --- secret -----------------------------------------------------------------

def _secret(sub) -> None:
    _, s = _group(sub, "secret", "store and use secrets by name (no command prints a value)")
    p = s.add_parser("set", help="store NAME; value from a no-echo prompt, or stdin when piped")
    p.add_argument("name")
    p.set_defaults(func=cmd_secret_set)
    p = s.add_parser("ls", help="list secret names and where they come from")
    p.set_defaults(func=cmd_secret_ls)
    p = s.add_parser("check", help="exit 0 if every NAME is set")
    p.add_argument("names", nargs="+")
    p.set_defaults(func=cmd_secret_check)
    p = s.add_parser("rm", help="delete NAME from the backend")
    p.add_argument("name")
    p.set_defaults(func=cmd_secret_rm)
    p = s.add_parser("exec", help="run a command with secrets in its env: exec NAME[=VAR]... -- cmd args",
                     usage="carhunt secret exec NAME[=VAR]... -- cmd [args...]")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_secret_exec)


def cmd_secret_set(a) -> int:
    try:
        secrets.check_name(a.name)
        if sys.stdin.isatty():
            v = getpass.getpass(f"{a.name}: ")
            if getpass.getpass("again: ") != v:
                _err("values differ; nothing stored")
                return 1
        else:
            v = sys.stdin.read().removesuffix("\n")
        where = secrets.set(a.name, v)
    except secrets.SecretError as e:
        _err(str(e))
        return 1
    print(f"stored {a.name} ({where})")
    return 0


def cmd_secret_ls(a) -> int:
    try:
        for name, src in secrets.names():
            print(f"{name}\t{src}")
    except secrets.SecretError as e:
        _err(str(e))
        return 1
    return 0


def cmd_secret_check(a) -> int:
    rc = 0
    for n in a.names:
        try:
            src = secrets.source(n)
        except secrets.SecretError as e:
            _err(str(e))
            return 2
        print(f"{n}: {'ok (' + src + ')' if src else 'missing'}")
        rc |= src is None
    return rc


def cmd_secret_rm(a) -> int:
    try:
        ok = secrets.delete(a.name)
    except secrets.SecretError as e:
        _err(str(e))
        return 1
    print(f"{a.name}: {'deleted' if ok else 'not found'}")
    return 0 if ok else 1


def cmd_secret_exec(a) -> int:
    rest = a.rest
    if "--" not in rest:
        _err("usage: carhunt secret exec NAME[=VAR]... -- cmd [args...]")
        return 2
    i = rest.index("--")
    specs, cmd = rest[:i], rest[i + 1:]
    if not specs or not cmd:
        _err("usage: carhunt secret exec NAME[=VAR]... -- cmd [args...]")
        return 2
    env = dict(os.environ)
    try:
        for spec in specs:
            name, _, var = spec.partition("=")
            env[var or name.upper().replace(".", "_").replace("-", "_")] = secrets.get(name)
    except (secrets.SecretError, KeyError) as e:
        _err(str(e))
        return 1
    try:
        os.execvpe(cmd[0], cmd, env)
    except OSError as e:
        _err(f"cannot run {cmd[0]}: {e.strerror}")
        return 127


# --- notify -----------------------------------------------------------------

def _agent_default() -> str | None:
    return os.environ.get("CARHUNT_AGENT") or os.environ.get("CARDB_AUTHOR")


def _notify(sub) -> None:
    _, s = _group(sub, "notify", "owner pushes (digest | ask | urgent) and agent inboxes")
    p = s.add_parser("send", help="push to the owner; FYI is refused by design")
    p.add_argument("text", help="message text, or - for stdin")
    p.add_argument("--agent", default=_agent_default(), help="sending agent (default $CARHUNT_AGENT)")
    p.add_argument("--kind", required=True, choices=None, help="digest | ask | urgent")
    p.add_argument("--buttons", help='choices for kind=ask, "A|B|C"')
    p.add_argument("--ask", action="store_true", help="free-text answer expected (force reply)")
    p.set_defaults(func=cmd_notify_send)

    pi, si = _group(s, "inbox", "an agent's inbox of owner replies and routed lines")
    for name, fn, h in (("list", cmd_inbox_list, "show items (unacked by default)"),
                        ("wait", cmd_inbox_wait, "block until an unacked item arrives"),
                        ("ack", cmd_inbox_ack, "mark items handled")):
        p = si.add_parser(name, help=h)
        p.add_argument("--agent", default=_agent_default())
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=fn)
        if name == "list":
            p.add_argument("--all", action="store_true", help="include acked items")
        if name == "wait":
            p.add_argument("--timeout", type=float, help="seconds (default: forever)")
            p.add_argument("--no-poll", action="store_true", help="don't drive the Telegram poller")
        if name == "ack":
            p.add_argument("ids", nargs="+")

    p = s.add_parser("poll", help="route Telegram replies into agent inboxes; flush held messages")
    p.add_argument("--once", action="store_true")
    p.add_argument("--timeout", type=int, default=25, help="long-poll seconds per round")
    p.set_defaults(func=cmd_notify_poll)


def _need_agent(a) -> str | None:
    if not a.agent:
        _err("--agent is required (or set CARHUNT_AGENT)")
        return None
    return a.agent


def cmd_notify_send(a) -> int:
    if not (agent := _need_agent(a)):
        return 2
    text = sys.stdin.read() if a.text == "-" else a.text
    buttons = [b.strip() for b in a.buttons.split("|")] if a.buttons else None
    try:
        r = notify.deliver(text.strip(), agent=agent, kind=a.kind, buttons=buttons, ask=a.ask)
    except notify.Refused as e:
        _err(f"refused: {e}")
        return EXIT_REFUSED
    except (notify.NotifyError, config.ConfigError, ValueError) as e:
        _err(f"failed: {e}")
        return EXIT_FAILED
    if r.status == "sent":
        print(f"sent ref={r.ref}" + (" (silent: quiet hours)" if r.silent else ""))
    elif r.status == "held":
        print(f"held until {r.until:%Y-%m-%d %H:%M} (quiet hours)")
    else:
        print("dropped (notify.backend: none)")
    return 0


def _print_items(items: list[dict], as_json: bool) -> None:
    for i in items:
        if as_json:
            print(json.dumps(i, ensure_ascii=False))
        else:
            re_ = f' re "{i["re_text"]}"' if i.get("re_text") else ""
            print(f"{i['id']}\t{i.get('ts', '')}\t{i.get('source', '')}{re_}\t{i.get('text', '')}")


def cmd_inbox_list(a) -> int:
    if not (agent := _need_agent(a)):
        return 2
    _print_items(notify.inbox(agent).list(unacked=not a.all), a.json)
    return 0


def cmd_inbox_wait(a) -> int:
    if not (agent := _need_agent(a)):
        return 2
    items = notify.inbox(agent).wait(a.timeout, poll=not a.no_poll)
    _print_items(items, a.json)
    return 0 if items else 1


def cmd_inbox_ack(a) -> int:
    if not (agent := _need_agent(a)):
        return 2
    unknown = notify.inbox(agent).ack(*a.ids)
    for i in unknown:
        _err(f"not in {agent}'s inbox: {i}")
    return 1 if unknown else 0


def cmd_notify_poll(a) -> int:
    from carhunt.core import lock

    try:
        if not isinstance(notify.backend(config.load_or_none()), notify.TelegramBackend):
            n = notify.flush()
            print(f"notify.backend is not telegram: nothing to poll (flushed {n} held)")
            return 0
    except (notify.NotifyError, config.ConfigError) as e:
        _err(str(e))
        return EXIT_FAILED
    while True:
        try:
            notify.flush()
            n = notify.poll(timeout=0 if a.once else a.timeout, wait_lock=0 if a.once else None)
            if a.once:
                print(f"routed {n}")
                return 0
        except lock.LockTimeout:
            _err("another process is polling")
            return 1
        except notify.NotifyError as e:
            _err(str(e))
            if a.once:
                return EXIT_FAILED
            import time

            time.sleep(10)


# --- doctor -----------------------------------------------------------------

def cmd_doctor(a) -> int:
    results = doctor.run_all()
    if a.json:
        print(json.dumps([c.to_dict() for c in results], indent=2))
    else:
        print(doctor.render(results))
    return doctor.exit_code(results)
