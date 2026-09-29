from __future__ import annotations
import importlib.metadata as md
import shutil
import sys
from pathlib import Path

venv = Path(sys.argv[1]).resolve()
dest = Path(sys.argv[2]).resolve()
site_candidates = list((venv / "lib").glob("python*/site-packages")) + [venv / "Lib" / "site-packages"]
site = next(path for path in site_candidates if path.is_dir())
dest.mkdir(parents=True, exist_ok=True)
for dist in md.distributions(path=[str(site)]):
    name = (dist.metadata.get("Name") or "unknown").replace("/", "_")
    files = list(dist.files or [])
    license_files = [p for p in files if ".dist-info/licenses/" in str(p).replace("\\", "/")]
    if not license_files:
        license_files = [p for p in files if Path(str(p)).name.lower() in {"license", "license.txt", "copying", "notice"}
                         and ".dist-info/" in str(p).replace("\\", "/")]
    for item in license_files:
        src = Path(dist.locate_file(item))
        if src.is_file():
            relative = Path(str(item).replace("\\", "/")).name
            out = dest / name / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
