"""Create a Windows package ZIP with POSIX entry separators, including hidden paths."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

stage = Path(sys.argv[1]).resolve()
archive = Path(sys.argv[2]).resolve()
archive.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
    for path in sorted(stage.rglob("*")):
        if path.is_file():
            bundle.write(path, path.relative_to(stage).as_posix())
