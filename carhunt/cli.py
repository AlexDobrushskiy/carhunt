"""`carhunt <group> …`: each package `carhunt/<pkg>/cli.py` with `register(subparsers)` adds its groups.

A plugin that fails to import or register prints a warning; the other groups still work.
Handlers return an int exit code (None = 0).
"""
from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from types import ModuleType

import carhunt


def discover(root: ModuleType = carhunt) -> list[tuple[str, ModuleType | None, str | None]]:
    """(package, cli module or None, error or None) for each package that has a cli.py."""
    out = []
    for m in sorted(pkgutil.iter_modules(root.__path__), key=lambda m: (m.name != "core", m.name)):
        if not m.ispkg:
            continue
        name = f"{root.__name__}.{m.name}.cli"
        try:
            out.append((m.name, importlib.import_module(name), None))
        except ModuleNotFoundError as e:
            if e.name != name:
                out.append((m.name, None, f"{type(e).__name__}: {e}"))
        except Exception as e:  # noqa: BLE001 - one broken plugin must not kill the CLI
            out.append((m.name, None, f"{type(e).__name__}: {e}"))
    return out


def build_parser(root: ModuleType = carhunt, *, warn=None) -> argparse.ArgumentParser:
    warn = warn or (lambda msg: print(f"carhunt: warning: {msg}", file=sys.stderr))
    p = argparse.ArgumentParser(prog="carhunt", description="Used-car search with Claude Code agents.")
    p.add_argument("--version", action="version", version=f"carhunt {carhunt.__version__}")
    sub = p.add_subparsers(dest="group", metavar="<group>")
    for pkg, mod, err in discover(root):
        if err:
            warn(f"plugin {pkg} not loaded ({err})")
            continue
        if not hasattr(mod, "register"):
            warn(f"plugin {pkg}: cli.py has no register(subparsers)")
            continue
        before = dict(sub.choices)
        try:
            mod.register(sub)
        except Exception as e:  # noqa: BLE001
            # drop half-registered groups so a later plugin can still use the name
            for k in set(sub.choices) - set(before):
                sub.choices.pop(k, None)
            sub._choices_actions[:] = [a for a in sub._choices_actions if a.dest in sub.choices]
            warn(f"plugin {pkg} failed to register ({type(e).__name__}: {e})")
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        # a group without a subcommand: show that group's help
        target = getattr(args, "_parser", None) or p
        target.print_help(sys.stderr)
        return 2
    try:
        return int(func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
