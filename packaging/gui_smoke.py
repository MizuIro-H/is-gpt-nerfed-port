from __future__ import annotations
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

exe = Path(sys.argv[1]).resolve()
env = os.environ.copy()
env["QT_QPA_PLATFORM"] = "offscreen"
tmp = Path(tempfile.mkdtemp(prefix="is-gpt-nerfed-gui-smoke-"))
shot = tmp / "demo.png"
try:
    result = subprocess.run([str(exe), "--demo", "--screenshot", str(shot)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", timeout=45)
    if result.returncode != 0:
        raise SystemExit(f"GUI demo exited {result.returncode}\n{result.stdout}\n{result.stderr}")
    if not shot.is_file() or shot.stat().st_size < 100:
        raise SystemExit(f"GUI did not render a demo screenshot\n{result.stdout}\n{result.stderr}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(f"offscreen GUI-to-core snapshot smoke passed: {exe}")
