#!/bin/sh
# Stable POSIX hook entry point; all hooks are best-effort and must never block Codex.
set -u
EVENT="${1:-}"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
NERFED_HOME="${NERFED_HOME:-$CODEX_HOME/is-gpt-nerfed}"
ROOT="${NERFED_PLUGIN_ROOT:-${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-}}}"
if [ -z "$ROOT" ] || [ ! -f "$ROOT/skills/is-gpt-nerfed/scripts/nerfed" ]; then
  ROOT="$NERFED_HOME/plugin"
fi
CORE="${NERFED_CORE_BIN:-}"
if [ -n "$CORE" ] && [ -x "$CORE" ]; then
  "$CORE" hook --event "$EVENT" || true
  exit 0
fi
if [ -f "$NERFED_HOME/runtime.sh" ]; then
  sh "$NERFED_HOME/runtime.sh" hook --event "$EVENT" || true
  exit 0
fi
if [ -z "$CORE" ] && [ -n "$ROOT" ]; then
  CANDIDATE="$(dirname "$ROOT")/nerfed-core"
  [ -x "$CANDIDATE" ] && CORE="$CANDIDATE"
fi
if [ -n "$CORE" ] && [ -x "$CORE" ]; then
  "$CORE" hook --event "$EVENT" || true
  exit 0
fi
RUNTIME="$NERFED_HOME/runtime.json"
if command -v python3 >/dev/null 2>&1 && [ -f "$RUNTIME" ]; then
  python3 -c 'import json,os,sys; c=json.load(open(sys.argv[1],encoding="utf-8")).get("command",[]); os.execvpe(c[0],c+["hook","--event",sys.argv[2]],os.environ)' "$RUNTIME" "$EVENT" 2>/dev/null || true
  exit 0
fi
if [ -n "$ROOT" ] && [ -f "$ROOT/skills/is-gpt-nerfed/scripts/nerfed" ] && command -v python3 >/dev/null 2>&1; then
  python3 "$ROOT/skills/is-gpt-nerfed/scripts/nerfed" hook --event "$EVENT" || true
fi
exit 0
