#!/usr/bin/env bash
set -euo pipefail

REF="${HCN_REF:-main}"
REPO="${HCN_REPO:-https://github.com/lnsflive/hermes-cursor-native.git}"
if [[ "$REPO" == file:* || -e "$REPO" ]]; then
  SPEC="$REPO"
else
  SPEC="git+${REPO}@${REF}"
fi

echo "Hermes Cursor Native bootstrap (${REF})"

CLI_PATH=""
if command -v uv >/dev/null 2>&1; then
  uv tool install --force "$SPEC"
else
  PYTHON=""
  for candidate in \
    python3 python3.13 python3.12 python3.11 \
    "$HOME/.hermes/hermes-agent/venv/bin/python"
  do
    if [[ "$candidate" == */* ]]; then
      resolved="$candidate"
      [[ -x "$resolved" ]] || continue
    else
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
      [[ -n "$resolved" ]] || continue
    fi
    if "$resolved" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
      PYTHON="$resolved"
      break
    fi
  done

  if [[ -z "$PYTHON" ]]; then
    echo "Python 3.11+ or uv is required. A git-installed Hermes runtime normally provides Python at ~/.hermes/hermes-agent/venv/bin/python." >&2
    exit 1
  fi

  BOOTSTRAP_VENV="${HCN_BOOTSTRAP_VENV:-${XDG_DATA_HOME:-$HOME/.local/share}/hermes-cursor-native/venv}"
  "$PYTHON" -m venv "$BOOTSTRAP_VENV"
  "$BOOTSTRAP_VENV/bin/python" -m pip install --upgrade "$SPEC"
  CLI_PATH="$BOOTSTRAP_VENV/bin/hermes-cursor-native"
fi

if [[ "${HCN_BOOTSTRAP_ONLY:-0}" == "1" ]]; then
  echo "Hermes Cursor Native CLI installed."
  exit 0
fi
if command -v hermes-cursor-native >/dev/null 2>&1; then
  exec hermes-cursor-native install
fi
if [[ -n "$CLI_PATH" ]]; then
  exec "$CLI_PATH" install
fi
exec uv tool run hermes-cursor-native install
