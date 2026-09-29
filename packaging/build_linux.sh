#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DIST_DIR="$ROOT/Linux/dist"
mkdir -p "$DIST_DIR"
[[ "$(ldd --version | head -1)" == *"2.35"* ]] || { echo "Linux build requires glibc 2.35; got $(ldd --version | head -1)" >&2; exit 2; }
PYTHON_BIN="${PYTHON_BIN:-python3}"
BUILD_DIR="${BUILD_DIR:-$ROOT/.build/linux}"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
if [[ -n "${BUILD_VENV:-}" ]]; then
  VENV="$BUILD_VENV"
  [[ -x "$VENV/bin/python" && -x "$VENV/bin/pyinstaller" ]] || { echo "BUILD_VENV lacks Python/PyInstaller: $VENV" >&2; exit 2; }
else
  VENV="$BUILD_DIR/venv"
  "$PYTHON_BIN" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -r requirements-build.txt
fi
"$VENV/bin/pyinstaller" --clean --noconfirm --workpath "$BUILD_DIR/pyinstaller-work" --distpath "$DIST_DIR" packaging/IsGPTNerfed.spec
"$VENV/bin/pyinstaller" --clean --noconfirm --workpath "$BUILD_DIR/pyinstaller-work" --distpath "$DIST_DIR" packaging/IsGPTNerfed-core.spec
"$VENV/bin/pyinstaller" --clean --noconfirm --onefile --name fake_codex \
  --add-data "tests/fixtures:fixtures" --distpath "$BUILD_DIR/fake-dist" --workpath "$BUILD_DIR/fake-work" tests/fake_codex.py
PATH="$VENV/bin:$PATH" NERFED_TEST_CODEX_BIN="$BUILD_DIR/fake-dist/fake_codex" \
  "$VENV/bin/python" -m unittest discover -s tests -v
STAGE="$BUILD_DIR/stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a "$DIST_DIR"/IsGPTNerfed/. "$STAGE/"
cp "$DIST_DIR"/nerfed-core "$STAGE/nerfed-core"
cp -a plugin "$STAGE/plugin"
cp -a .agents "$STAGE/.agents"
cp README-CROSSPLATFORM.md "$STAGE/README-CROSSPLATFORM.md"
"$VENV/bin/python" packaging/gui_smoke.py "$STAGE/IsGPTNerfed"
"$VENV/bin/python" packaging/smoke.py "$STAGE/nerfed-core" "$STAGE" "$BUILD_DIR/fake-dist/fake_codex"
"$VENV/bin/python" packaging/copy_licenses.py "$VENV" "$STAGE/licenses"
cp packaging/NOTICE "$STAGE/NOTICE"
mkdir -p "$DIST_DIR"
tar -C "$STAGE" -czf "$DIST_DIR"/IsGPTNerfed-0.5.2-linux-x86_64.tar.gz .
mkdir -p "$BUILD_DIR/wsl"
cp "$DIST_DIR"/nerfed-core "$BUILD_DIR/wsl/nerfed-core"
cp -a plugin "$BUILD_DIR/wsl/plugin"
cp -a .agents "$BUILD_DIR/wsl/.agents"
cp -a "$STAGE/licenses" "$BUILD_DIR/wsl/licenses"
cp packaging/NOTICE "$BUILD_DIR/wsl/NOTICE"
tar -C "$BUILD_DIR/wsl" -czf "$DIST_DIR"/nerfed-core-linux-x86_64.tar.gz .
(cd "$DIST_DIR" && sha256sum IsGPTNerfed-0.5.2-linux-x86_64.tar.gz > IsGPTNerfed-0.5.2-linux-x86_64.tar.gz.sha256)
(cd "$DIST_DIR" && sha256sum nerfed-core-linux-x86_64.tar.gz > nerfed-core-linux-x86_64.tar.gz.sha256)
echo "Built $(ldd --version | head -1) package: $DIST_DIR/IsGPTNerfed-0.5.2-linux-x86_64.tar.gz"
