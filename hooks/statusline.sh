#!/usr/bin/env bash
# Claude Code statusLine for carhunt agents: prints "ctx:N%" and records it for `carhunt agent ctx`.
# Handover is measured, not felt: agents hand over at orchestrate.handover_ctx_pct of context.
# Already have a statusline? Add the two marked lines to yours (see docs/orchestrate.md).
input=$(cat)
pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // empty' 2>/dev/null)
model=$(printf '%s' "$input" | jq -r '.model.display_name // empty' 2>/dev/null)
dir=$(printf '%s' "$input" | jq -r '.workspace.current_dir // .cwd // empty' 2>/dev/null)
# >>> carhunt ctx >>>
sid=${CARHUNT_SESSION_ID:-$AGTERM_SESSION_ID}
[ -n "$pct" ] && [ -n "$sid" ] && [ -n "$CARHUNT_HOME" ] && mkdir -p "$CARHUNT_HOME/ctx" && printf '{"pct": %.0f, "ts": %s}\n' "$pct" "$(date +%s)" > "$CARHUNT_HOME/ctx/$sid.json"
# <<< carhunt ctx <<<
out="${dir/#$HOME/~}"
[ -n "$model" ] && out="$out | $model"
[ -n "$pct" ] && out="$out | $(printf 'ctx:%.0f%%' "$pct")"
[ -n "${CARHUNT_AGENT:-}" ] && out="$out | $CARHUNT_AGENT"
printf '%s\n' "$out"
