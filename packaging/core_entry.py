"""PyInstaller entry point for the independent nerfed CLI executable."""
from __future__ import annotations
import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        # Keep plugin data replaceable and shared with the desktop package.
        root = Path(sys.executable).resolve().parent
        plugin_root = root / "plugin"
        os.environ["NERFED_PLUGIN_ROOT"] = str(plugin_root)
        os.environ["NERFED_CORE_BIN"] = sys.executable
    else:
        plugin_root = Path(__file__).resolve().parents[1] / "plugin"
    script = plugin_root / "skills" / "is-gpt-nerfed" / "scripts" / "nerfed"
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
