#!/bin/sh
# is-gpt-nerfed uninstaller. Add --purge to also delete the local ledger (~/.codex/is-gpt-nerfed).
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT/bin/nerfed" teardown "$@"
