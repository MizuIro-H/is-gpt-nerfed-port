"""GUI executable entry point (also used by PyInstaller)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The PyInstaller analysis root and the source checkout root both contain the
# `desktop` package. Add the source root when this file is run directly.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.main import run


def main() -> int:
    parser = argparse.ArgumentParser(description="is-gpt-nerfed desktop inspector")
    parser.add_argument("--demo", action="store_true", help="show synthetic offline data in an isolated temporary home")
    parser.add_argument("--screenshot", help="save the first rendered window image (intended for offline demo review)")
    args, qt_args = parser.parse_known_args()
    # Qt receives only its own arguments; the product intentionally has no CLI mode.
    sys.argv = [sys.argv[0], *qt_args]
    return run(demo=args.demo, screenshot=args.screenshot)


if __name__ == "__main__":
    raise SystemExit(main())
