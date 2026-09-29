#!/bin/sh
# Adopt a generated 1024x1024 PNG as the app icon and plugin logo, then rebuild and reinstall the menu bar app.
# Usage: tools/set_icon.sh path/to/icon.png
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:?usage: tools/set_icon.sh <png>}"
sips -z 1024 1024 "$SRC" --out "$ROOT/macos/icon.png" >/dev/null
sips -z 512 512 "$SRC" --out "$ROOT/plugin/assets/logo.png" >/dev/null
echo "icon → macos/icon.png, logo → plugin/assets/logo.png"
"$ROOT/macos/build.sh" --install
echo "run ./install.sh to refresh the plugin logo Codex shows"
