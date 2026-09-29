"""Offline frozen-Windows-to-WSL launch smoke test.

Run this from native Windows with the packaged-build venv and an explicit
installed distro, for example:

  .build\\windows\\venv\\Scripts\\python.exe packaging\\wsl_smoke.py \
      --distro Ubuntu --stage .build\\windows\\stage

Only a fresh /tmp/is-gpt-nerfed-wsl-smoke-<uuid> tree in that distro is used;
the script removes it in a finally block. It requests `snapshot --demo`, never
runs setup, and never invokes a Codex binary or a model.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distro", required=True, help="installed WSL distribution to test")
    parser.add_argument("--stage", required=True, type=Path, help="Windows package staging directory")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Run this smoke test with native Windows Python so it exercises the packaged Windows backend.")
    stage = args.stage.resolve()
    gui = stage / "IsGPTNerfed.exe"
    if not gui.is_file():
        gui = stage / "IsGPTNerfed" / "IsGPTNerfed.exe"
    archive = stage / "wsl" / "nerfed-core-linux.tar.gz"
    if not gui.is_file() or not archive.is_file():
        raise SystemExit(f"Expected staged GUI and WSL archive under {stage}; found GUI={gui.is_file()}, archive={archive.is_file()}.")

    repo = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo))
    from desktop.backend import Backend

    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        raise SystemExit("wsl.exe was not found on PATH.")

    temporary_home = "/tmp/is-gpt-nerfed-wsl-smoke-" + uuid.uuid4().hex
    # Backend(demo=True) avoids even creating the user's application-config
    # directory. Turn off its ordinary demo env branch after construction so
    # the generated frozen command uses this test's explicit temporary profile.
    backend = Backend(demo=True)
    backend.demo = False
    backend.profile = {
        "kind": "wsl",
        "distro": args.distro,
        "codex_home": temporary_home + "/codex",
        "codex_bin": "",
    }

    old_executable = sys.executable
    was_frozen = getattr(sys, "frozen", None)
    try:
        # Make app_root() resolve exactly as it does in the staged frozen app.
        sys.executable = str(gui)
        sys.frozen = True
        program, argv, _env = backend._command(["snapshot", "--demo", "--json"])
        if program.lower() != "wsl.exe" and Path(program).name.lower() != "wsl.exe":
            raise RuntimeError(f"Backend did not choose wsl.exe: {program}")

        # Run the backend-generated argv unchanged except for placing a temporary
        # HOME in front of its shell. CODEX_HOME points into the same disposable
        # tree, so both runtime deployment and the demo ledger are isolated.
        if len(argv) < 6 or argv[2] != "--exec" or argv[3] != "sh":
            raise RuntimeError(f"Unexpected frozen backend argv shape: {argv[:6]!r}")
        isolated_argv = [*argv[:3], "env", f"HOME={temporary_home}", *argv[3:]]
        result = subprocess.run([program, *isolated_argv], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
        if result.returncode != 0:
            raise RuntimeError(f"WSL demo snapshot exited {result.returncode}:\n{result.stderr[-4000:]}\n{result.stdout[-1000:]}")
        try:
            snapshot = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError(f"WSL demo did not return JSON: {exc}\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}") from exc
        threads = snapshot.get("threads") if isinstance(snapshot, dict) else None
        if not isinstance(threads, list) or len(threads) != 6:
            raise RuntimeError(f"Expected six synthetic demo threads, got {len(threads) if isinstance(threads, list) else type(threads).__name__}.")

        remote_root = f"{temporary_home}/.local/share/is-gpt-nerfed/runtime/0.5.2-crossplatform"
        check = ("set -eu; "
                 f"test -x {remote_root}/nerfed-core; "
                 f"test -f {remote_root}/plugin/assets/modeltrace/unified_bank.json; "
                 f"test -f {remote_root}/.agents/plugins/marketplace.json; "
                 "printf 'WSL_DEPLOYMENT_OK\\n'")
        verify = subprocess.run([program, "-d", args.distro, "--exec", "env", f"HOME={temporary_home}",
                                 "sh", "-lc", check], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30)
        if verify.returncode != 0 or "WSL_DEPLOYMENT_OK" not in verify.stdout:
            raise RuntimeError(f"WSL deployment resource check failed:\n{verify.stdout}\n{verify.stderr}")
        print(f"WSL frozen runtime smoke passed for {args.distro}: {len(threads)} demo threads; core, fingerprint bank, and marketplace resources deployed under temporary HOME.")
        return 0
    finally:
        sys.executable = old_executable
        if was_frozen is None:
            del sys.frozen
        else:
            sys.frozen = was_frozen
        cleanup = subprocess.run([wsl, "-d", args.distro, "--exec", "sh", "-lc",
                                  "rm -rf -- " + __import__("shlex").quote(temporary_home)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if cleanup.returncode != 0:
            print(f"Warning: temporary WSL smoke tree cleanup failed: {cleanup.stderr[-1000:]}", file=sys.stderr)
        if backend._temp:
            backend._temp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
