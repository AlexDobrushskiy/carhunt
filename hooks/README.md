# hooks

Claude Code hooks. Owner: orchestrate. Install: `carhunt hooks install` (diff + ask, never touches foreign entries).

| file | what |
|---|---|
| `carhunt_hook.py` | `secret-guard`, `send-guard`, `identity-pre/post`, `mailbox` (stdlib only) |
| `statusline.sh` | statusline printing `ctx:N%` and recording it for `carhunt agent ctx` |

Details and the why of each guard: [docs/orchestrate.md](../docs/orchestrate.md#guard-hooks-hookscarhunt_hookpy-stdlib-only).
