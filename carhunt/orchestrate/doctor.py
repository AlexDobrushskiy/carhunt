"""`carhunt doctor` checks for orchestrate: agterm, agent CLI, statusline ctx, hooks, schedule, state."""
from __future__ import annotations

import shutil
import subprocess

from carhunt.core.doctor import Check

from . import settings


def _agterm() -> Check:
    ctl = shutil.which("agtermctl")
    if not ctl:
        return Check("orchestrate.agterm", "fail", "agtermctl not on PATH",
                     "install agterm (https://github.com/umputun/agterm) and enable its CLI")
    res = subprocess.run([ctl, "version"], capture_output=True, text=True, check=False, timeout=10)
    if res.returncode != 0:
        return Check("orchestrate.agterm", "fail", "agterm control socket not reachable", "start agterm")
    return Check("orchestrate.agterm", "ok", (res.stdout.strip().splitlines() or [""])[0])


def _agent_cli(config) -> Check:
    cli = settings.get(config, "orchestrate.agent_cli", "claude")
    if shutil.which(cli):
        return Check("orchestrate.agent_cli", "ok", cli)
    return Check("orchestrate.agent_cli", "fail", f"{cli} not on PATH",
                 "install Claude Code (npm i -g @anthropic-ai/claude-code) or set orchestrate.agent_cli")


def _statusline() -> Check:
    from . import hooks
    status, cmd = hooks.statusline_status(hooks.settings_path())
    if status == "none":
        return Check("orchestrate.statusline", "fail", "no statusLine: context % can't be measured",
                     "carhunt hooks statusline")
    if not hooks.probe_statusline(cmd):
        return Check("orchestrate.statusline", "warn", "statusLine doesn't print ctx:N%",
                     "add the 'carhunt ctx' lines from hooks/statusline.sh to your statusline")
    return Check("orchestrate.statusline", "ok", f"{status} statusline prints ctx:N%")


def _hooks() -> Check:
    from . import hooks
    path = hooks.settings_path()
    try:
        _, _, diff = hooks.plan(path)
    except hooks.HooksError as e:
        return Check("orchestrate.hooks", "fail", str(e), "fix settings.json by hand")
    if diff:
        return Check("orchestrate.hooks", "warn", "guard hooks missing or outdated", "carhunt hooks install")
    return Check("orchestrate.hooks", "ok", "guard hooks installed")


def _schedule(config) -> Check:
    from . import schedule
    want = {j["label"] for j in schedule.jobs(config)}
    have = {p.stem for p in schedule.installed()}
    if want - have:
        return Check("orchestrate.schedule", "warn", f"not installed: {', '.join(sorted(want - have))}",
                     "carhunt schedule install")
    return Check("orchestrate.schedule", "ok", f"{len(want)} launchd jobs")


def _states() -> Check:
    from . import state
    bad = []
    for role in state.roles():
        try:
            state.validate(state.read(role))
        except Exception as e:  # noqa: BLE001
            bad.append(f"{role}: {e}")
    if bad:
        return Check("orchestrate.state", "fail", "; ".join(bad), "carhunt state validate")
    return Check("orchestrate.state", "ok", f"{len(state.roles())} agent states valid")


def checks() -> list[Check]:
    config = settings.load()
    out = []
    for fn in (_agterm, lambda: _agent_cli(config), _statusline, _hooks, lambda: _schedule(config), _states):
        try:
            out.append(fn())
        except Exception as e:  # noqa: BLE001 - a broken check is a failed check
            out.append(Check("orchestrate", "fail", f"check crashed: {e}"))
    return out
