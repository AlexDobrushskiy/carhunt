# hooks

Claude Code hooks. Owner: orchestrate. Install: `carhunt hooks install` → `$CARHUNT_HOME/claude/settings.json`, passed to agents with `claude --settings` (diff + ask, never touches foreign entries).

| file | what |
|---|---|
| `carhunt_hook.py` | `secret-guard`, `send-guard`, `mailbox` (stdlib only); identity leases = `browsers/bin/pw-identity hook`, merged by the same install |
| `statusline.sh` | statusline printing `ctx:N%` and recording it for `carhunt agent ctx` |

Details and the why of each guard: [docs/orchestrate.md](../docs/orchestrate.md#guard-hooks-hookscarhunt_hookpy-stdlib-only).
