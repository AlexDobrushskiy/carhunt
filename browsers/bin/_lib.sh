# shellcheck shell=bash
# Shared helpers for browsers/bin/* (sourced, not executed). A tool sources it with:
#   . "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")/_lib.sh"   (see the tools for the symlink-safe form)
#
#   carhunt_repo     the repo root
#   carhunt_python   $CARHUNT_PYTHON → <repo>/.venv/bin/python → python3
#   carhunt_home     $CARHUNT_HOME → ~/.carhunt

_carhunt_resolve() {  # $1 = path → real path with symlinks followed (macOS has no GNU readlink -f before 12.3)
  local p="$1" dir
  while [ -L "$p" ]; do
    dir="$(cd -P "$(dirname "$p")" && pwd)"
    p="$(readlink "$p")"
    case "$p" in /*) ;; *) p="$dir/$p" ;; esac
  done
  echo "$(cd -P "$(dirname "$p")" && pwd)/$(basename "$p")"
}

# This file lives in <repo>/browsers/bin/.
CARHUNT_REPO="$(cd -P "$(dirname "$(_carhunt_resolve "${BASH_SOURCE[0]}")")/../.." && pwd)"

carhunt_repo() { echo "$CARHUNT_REPO"; }

carhunt_python() {
  if [ -n "${CARHUNT_PYTHON:-}" ]; then echo "$CARHUNT_PYTHON"; return; fi
  if [ -x "$CARHUNT_REPO/.venv/bin/python" ]; then echo "$CARHUNT_REPO/.venv/bin/python"; return; fi
  command -v python3 || { echo "carhunt: no python3 (set CARHUNT_PYTHON)" >&2; return 1; }
}

carhunt_home() { echo "${CARHUNT_HOME:-$HOME/.carhunt}"; }

# `python -m carhunt.access…` must find the package even without an editable install.
export PYTHONPATH="$CARHUNT_REPO${PYTHONPATH:+:$PYTHONPATH}"
