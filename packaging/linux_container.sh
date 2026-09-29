#!/usr/bin/env bash
set -euo pipefail
[[ "$(ldd --version | head -1)" == *"2.35"* ]] || { echo "Builder image must use glibc 2.35; got $(ldd --version | head -1)" >&2; exit 2; }
BUILD_VENV=/opt/build-venv bash packaging/build_linux.sh
