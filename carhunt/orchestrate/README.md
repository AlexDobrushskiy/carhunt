# carhunt/orchestrate

Agent sessions (agterm), state + handover, launch, messages, pause, digest, learning, launchd schedule, hook install. Owner: orchestrate. Docs: [docs/orchestrate.md](../../docs/orchestrate.md).

| file | what |
|---|---|
| `session.py` | backend interface + agterm backend (spawn/send/screen/ctx_percent/close/alive) |
| `launch.py` | render templates + role brief → `$CARHUNT_HOME/agents/<role>/brief.md`, spawn |
| `state.py` | state.json (locked, schema-checked), handover / takeover / cleanup |
| `msg.py` · `pause.py` · `digest.py` · `learn.py` · `schedule.py` · `hooks.py` | one CLI group each |
| `cli.py` · `doctor.py` | `register(subparsers)` · `checks()` |
| `settings.py` | config view: core config + orchestrate defaults (plain dict, briefs render from it) |

Tests: `pytest carhunt/orchestrate` (fake session backend, no network).
