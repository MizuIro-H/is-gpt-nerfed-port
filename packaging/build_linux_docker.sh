#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
docker build -f "$ROOT/packaging/linux-builder.Dockerfile" -t is-gpt-nerfed-linux-builder:22.04 "$ROOT"
docker run --rm \
  -v "$ROOT:/src" -w /src \
  is-gpt-nerfed-linux-builder:22.04 bash packaging/linux_container.sh
