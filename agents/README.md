# agents

Role briefs and templates that `carhunt agent launch ROLE` renders into `$CARHUNT_HOME/agents/ROLE/brief.md`. Owner: orchestrate (role briefs: the module named in [roles/](roles/README.md)). Doc: [docs/orchestrate.md](../docs/orchestrate.md).

| path | what |
|---|---|
| [roles/](roles/README.md) | one `brief.md` per role |
| [templates/](templates/README.md) | `common.md` (prepended to every brief), side task, lessons, digest layout |
| `state.schema.json` | schema of each agent's `state.json` (`carhunt state validate`) |
