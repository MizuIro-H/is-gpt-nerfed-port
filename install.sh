#!/bin/sh
# is-gpt-nerfed installer — registers the plugin with Codex (desktop app or CLI), offers to trust the plugin's
# hooks (Codex skips untrusted hooks), runs doctor.
# Usage: ./install.sh [--trust-hooks | --no-trust]
#        (set CODEX_BIN=/path/to/codex if codex is not on PATH and not in the ChatGPT app)
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$ROOT/plugin/skills/is-gpt-nerfed/scripts/nerfed" "$ROOT/bin/nerfed" 2>/dev/null || true
if [ -n "${CODEX_BIN:-}" ]; then
  "$ROOT/bin/nerfed" config init >/dev/null
  "$ROOT/bin/nerfed" config set codex_bin "$CODEX_BIN"
fi
"$ROOT/bin/nerfed" setup "$@"
status=$?
# Put `nerfed` on PATH when ~/.local/bin exists (created by pipx, uv, …); otherwise say how.
if [ -d "$HOME/.local/bin" ] && [ -w "$HOME/.local/bin" ]; then
  ln -sf "$ROOT/bin/nerfed" "$HOME/.local/bin/nerfed" && echo "linked nerfed → $HOME/.local/bin/nerfed"
else
  echo "tip: add $ROOT/bin to PATH, or: ln -s $ROOT/bin/nerfed /usr/local/bin/nerfed"
fi
exit $status
