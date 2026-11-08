# agents/templates

Owner: orchestrate. Placeholders are `{dotted.key}` (config keys + `agent.*`, `home`, `date`, `learned.dir`, per-launch `--var` values, `{variant}` for `BASE-VARIANT` roles); unknown keys fail the launch; `{{x}}` renders a literal `{x}`. See docs/orchestrate.md § Launch values.

| file | used by |
|---|---|
| `common.md` | prepended to every role brief at `carhunt agent launch` |
| `side-task.md` | `carhunt agent side NAME --task-file F` (`{task.name}`, `{task.body}`) |
| `lessons.md` | format of each agent's nightly `lessons/<date>.md` |
| `digest.txt` | `carhunt digest` layout |
