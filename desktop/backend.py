"""Cross-platform, asynchronous launcher for the nerfed CLI.

All Codex-facing work is delegated to the existing CLI.  This module owns only
the desktop target profile and process boundary; it never edits Codex config.
"""
from __future__ import annotations

import json
import hashlib
import os
import platform
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QStandardPaths, Signal


APP_VERSION = "0.5.3-crossplatform"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def plugin_root() -> Path:
    root = app_root() / "plugin"
    if root.is_dir():
        return root
    if getattr(sys, "frozen", False) and (app_root().parent / "plugin").is_dir():
        return app_root().parent / "plugin"
    return root


class ProfileStore:
    """Small JSON store in the platform's standard per-user config directory."""

    def __init__(self, create: bool = True) -> None:
        base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
        self.path = base / "profile.json"
        if create:
            base.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("kind") in ("native", "wsl"):
                return {k: value[k] for k in ("kind", "distro", "codex_home", "codex_bin") if k in value}
        except (OSError, ValueError):
            pass
        if sys.platform == "win32":
            raw = os.environ.get("CODEX_HOME", "")
            # Windows UNC is only a hint to select its owning WSL distro. Never use
            # that path as a Native home (or as a second copy of the same home).
            match = re.match(r"^\\\\(?:wsl\.localhost|wsl\$)\\([^\\]+)\\?(.*)$", raw, re.IGNORECASE)
            if match and match.group(1):
                return {"kind": "wsl", "distro": match.group(1), "codex_home": "", "codex_bin": ""}
            return {"kind": "native", "distro": "", "codex_home": "", "codex_bin": ""}
        return {"kind": "native", "distro": "", "codex_home": "", "codex_bin": ""}

    def save(self, value: dict) -> None:
        safe = {"kind": value.get("kind", "native"), "distro": value.get("distro", ""),
                "codex_home": value.get("codex_home", ""), "codex_bin": value.get("codex_bin", "")}
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)


class Backend(QObject):
    snapshotReady = Signal(dict)
    processFinished = Signal(str, int, str, str)
    processStarted = Signal(str)
    error = Signal(str)
    distrosReady = Signal(list)

    def __init__(self, demo: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.demo = demo
        self.profile_store = ProfileStore(create=not demo)
        self.profile = {"kind": "native", "distro": "", "codex_home": "", "codex_bin": ""} if demo else self.profile_store.load()
        self._active: dict[str, QProcess] = {}
        self._generation = 0
        self._wsl_payload_cache: tuple[Path, int, int, str] | None = None
        self._temp = tempfile.TemporaryDirectory(prefix="is-gpt-nerfed-demo-") if demo else None
        self._demo_id = Path(self._temp.name).name if self._temp else ""
        self._demo_root = Path(self._temp.name) if self._temp else Path(tempfile.gettempdir()) / ("is-gpt-nerfed-demo-" + self._demo_id)

    @property
    def busy(self) -> set[str]:
        return set(self._active)

    def save_profile(self, value: dict) -> bool:
        if self.demo:
            self.profile = dict(value)
            return True
        normalized = {"kind": value.get("kind", "native"), "distro": value.get("distro", ""),
                      "codex_home": value.get("codex_home", ""), "codex_bin": value.get("codex_bin", "")}
        if normalized == self.profile:
            return True
        blocked = sorted(k for k in self._active if k not in ("snapshot",))
        if blocked:
            self.error.emit("Wait for the active operation to finish before changing the backend profile.")
            return False
        self._generation += 1
        old = self._active.pop("snapshot", None)
        if old is not None:
            old.kill()
            old.deleteLater()
        self.profile = normalized
        self.profile_store.save(self.profile)
        return True

    def discover_distros(self) -> None:
        if sys.platform != "win32":
            self.distrosReady.emit([])
            return
        proc = QProcess(self)
        proc.setProgram(shutil.which("wsl.exe") or "wsl.exe")
        proc.setArguments(["--list", "--quiet"])
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        proc.finished.connect(lambda code, _status, p=proc: self._distros_done(p, code))
        proc.errorOccurred.connect(lambda _e, p=proc: (self.distrosReady.emit([]), p.deleteLater()))
        proc.start()

    def _distros_done(self, proc: QProcess, code: int) -> None:
        raw = bytes(proc.readAllStandardOutput())
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            out = raw.decode("utf-16", "replace")
        else:
            out = raw.decode("utf-8-sig", "replace")
        rows = [x.strip().replace("\x00", "").lstrip("\ufeff") for x in out.splitlines() if x.strip()]
        self.distrosReady.emit(rows if code == 0 else [])
        proc.deleteLater()

    def run(self, args: list[str], key: str | None = None, timeout_ms: int | None = None) -> bool:
        if self.demo and args and args[0] not in ("snapshot",):
            self.error.emit("Demo mode is offline. Actions that can alter data or contact a model are disabled.")
            return False
        key = key or (args[0] if args else "command")
        if key in self._active:
            return False
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        env = QProcessEnvironment.systemEnvironment()
        if self.profile.get("kind") == "wsl" and sys.platform == "win32":
            # Do not allow a Windows CODEX_HOME (often a WSL UNC path) to become
            # the WSL process's home. The WSL CLI then resolves its own $HOME.
            env.remove("CODEX_HOME")
            env.remove("NERFED_HOME")
        if self.demo:
            env.insert("CODEX_HOME", self._path(self._demo_root / "codex"))
            env.insert("NERFED_HOME", self._path(self._demo_root / "nerfed"))
        else:
            home = str(self.profile.get("codex_home") or "").strip()
            binary = str(self.profile.get("codex_bin") or "").strip()
            if home:
                env.insert("CODEX_HOME", home)
            if binary:
                env.insert("CODEX_BIN", binary)
        if getattr(sys, "frozen", False):
            # Start the bundled core with its own PyInstaller runtime. In
            # particular, do not let a frozen GUI's bootloader state bleed into
            # its separately frozen child process.
            env.insert("PYINSTALLER_RESET_ENVIRONMENT", "1")
            if not self.demo:
                env.insert("NERFED_CORE_BIN", str(app_root() / ("nerfed-core.exe" if sys.platform == "win32" else "nerfed-core")))
        env.insert("NERFED_PLUGIN_ROOT", str(plugin_root()))
        try:
            command, argv, extra_env = self._command(args)
        except (OSError, RuntimeError, ValueError) as exc:
            self.error.emit(str(exc))
            return False
        for k, v in extra_env.items():
            env.insert(k, v)
        process.setProgram(command)
        process.setArguments(argv)
        process.setProcessEnvironment(env)
        process.setProperty("profileGeneration", self._generation)
        self._active[key] = process
        process.finished.connect(lambda code, _status, k=key, p=process: self._finished(k, p, code))
        process.errorOccurred.connect(lambda err, k=key, p=process: self._failed(k, p, err))
        process.start()
        if timeout_ms:
            # QTimer keeps timeout handling on the event loop.
            from PySide6.QtCore import QTimer
            timer = QTimer(process)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda p=process: p.kill() if p.state() != QProcess.ProcessState.NotRunning else None)
            timer.start(timeout_ms)
        self.processStarted.emit(key)
        return True

    def snapshot(self) -> bool:
        return self.run(["snapshot", "--json"] + (["--demo"] if self.demo else []), key="snapshot", timeout_ms=25000)

    def _command(self, args: list[str]) -> tuple[str, list[str], dict[str, str]]:
        kind = self.profile.get("kind", "native")
        if kind == "wsl" and sys.platform == "win32":
            wsl = shutil.which("wsl.exe") or "wsl.exe"
            distro = str(self.profile.get("distro") or "").strip()
            if not distro:
                raise RuntimeError("Select a WSL distribution in Settings first.")
            core, root, is_source = self._wsl_paths()
            env_args = ["env", "-u", "CODEX_HOME", "-u", "NERFED_HOME", "-u", "CODEX_BIN",
                        "-u", "NERFED_PLUGIN_ROOT", "-u", "NERFED_CORE_BIN"]
            home = str(self.profile.get("codex_home") or "").strip()
            binary = str(self.profile.get("codex_bin") or "").strip()
            if home:
                if home.startswith("\\\\") or re.match(r"^[A-Za-z]:[\\/]", home):
                    raise ValueError("A WSL Codex home override must be a Linux path such as /home/name/.codex.")
                env_args.append("CODEX_HOME=" + home)
            if binary:
                env_args.append("CODEX_BIN=" + binary)
            if self.demo:
                # An isolated, stable temporary tree inside this distro. `--demo`
                # snapshot is synthetic; all CLI writes still stay inside it.
                env_args.extend(["CODEX_HOME=/tmp/is-gpt-nerfed-demo-" + self._demo_id + "/codex",
                                 "NERFED_HOME=/tmp/is-gpt-nerfed-demo-" + self._demo_id + "/nerfed"])
            if is_source:
                script = (f"script=$(wslpath -a {shlex.quote(core)}); "
                          f"root=$(wslpath -a {shlex.quote(root)}); "
                          f"exec env {' '.join(shlex.quote(x) for x in env_args)} NERFED_PLUGIN_ROOT=\"$root\" "
                          f"python3 \"$script\" " + " ".join(shlex.quote(x) for x in args))
                return wsl, ["-d", distro, "--exec", "sh", "-lc", script], {}
            # Extract only the bundled Linux runtime and plugin resources into
            # the distro's Linux filesystem. Shell arguments are quoted.
            archive = self._archive_path()
            if not archive.is_file():
                raise RuntimeError(f"Bundled WSL core archive is missing: {archive}")
            stat = archive.stat()
            cache = self._wsl_payload_cache
            if cache and cache[:3] == (archive, stat.st_size, stat.st_mtime_ns):
                digest = cache[3]
            else:
                hasher = hashlib.sha256()
                with archive.open("rb") as payload:
                    for block in iter(lambda: payload.read(1024 * 1024), b""):
                        hasher.update(block)
                digest = hasher.hexdigest()
                self._wsl_payload_cache = (archive, stat.st_size, stat.st_mtime_ns, digest)
            script = (f'dest="$HOME/.local/share/is-gpt-nerfed/runtime/{APP_VERSION}"; expected={digest}; '
                      f'if [ ! -x "$dest/nerfed-core" ] || [ ! -f "$dest/.payload-sha256" ] || '
                      f'[ "$(cat "$dest/.payload-sha256")" != "$expected" ]; then '
                      f'tmp="$dest.stage.$$"; old="$dest.previous.$$"; rm -rf "$tmp" "$old"; mkdir -p "$tmp" || exit 1; '
                      f'tar -xzf "$(wslpath -a {shlex.quote(str(archive))})" -C "$tmp" || {{ rm -rf "$tmp"; exit 1; }}; '
                      f'test -x "$tmp/nerfed-core" && test -f "$tmp/plugin/assets/modeltrace/unified_bank.json" || '
                      f'{{ rm -rf "$tmp"; echo "WSL runtime payload is incomplete" >&2; exit 1; }}; '
                      f'printf "%s\\n" "$expected" > "$tmp/.payload-sha256"; '
                      f'if [ -e "$dest" ]; then mv "$dest" "$old" || {{ rm -rf "$tmp"; exit 1; }}; fi; '
                      f'mv "$tmp" "$dest" || {{ [ ! -e "$old" ] || mv "$old" "$dest"; exit 1; }}; rm -rf "$old"; fi; '
                      + " ".join(shlex.quote(x) for x in env_args)
                      + f' NERFED_PLUGIN_ROOT="$dest/plugin" NERFED_CORE_BIN="$dest/nerfed-core" "$dest/nerfed-core" '
                      + " ".join(shlex.quote(x) for x in args))
            return wsl, ["-d", distro, "--exec", "sh", "-lc", script], {}
        if not self.demo and sys.platform == "win32" and kind == "native":
            raw_home = os.environ.get("CODEX_HOME", "")
            selected_home = str(self.profile.get("codex_home") or "").strip()
            windows_unc_home = lambda value: bool(re.match(r"^\\\\(?:wsl\.localhost|wsl\$)\\", value, re.IGNORECASE))
            if windows_unc_home(selected_home) or (windows_unc_home(raw_home) and not selected_home):
                raise RuntimeError("This Windows CODEX_HOME belongs to WSL. Select that WSL distribution or set an explicit Native Codex home.")
        if getattr(sys, "frozen", False):
            core = app_root() / ("nerfed-core.exe" if sys.platform == "win32" else "nerfed-core")
            return str(core), args, {}
        script = app_root() / "plugin" / "skills" / "is-gpt-nerfed" / "scripts" / "nerfed"
        return sys.executable, [str(script), *args], {}

    def _wsl_paths(self) -> tuple[str, str, bool]:
        if getattr(sys, "frozen", False):
            # Force use of the payload on packaged Windows builds.
            return "", "", False
        script = app_root() / "plugin" / "skills" / "is-gpt-nerfed" / "scripts" / "nerfed"
        plugin = plugin_root()
        # `wslpath` is evaluated inside the selected distribution, preserving
        # arbitrary drive letters and mount configuration without invoking a shell
        # with user input. Use a tiny fixed shell expression; these paths are app paths.
        return str(script), str(plugin), True

    def _archive_path(self) -> Path:
        candidates = (app_root().parent / "wsl" / "nerfed-core-linux.tar.gz",
                      app_root() / "wsl" / "nerfed-core-linux.tar.gz")
        return next((p for p in candidates if p.is_file()), candidates[0])

    @staticmethod
    def _path(path: Path) -> str:
        return str(path)

    def _finished(self, key: str, process: QProcess, code: int) -> None:
        stdout = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        stderr = bytes(process.readAllStandardError()).decode("utf-8", "replace")
        if self._active.get(key) is process:
            self._active.pop(key, None)
        if int(process.property("profileGeneration") or 0) != self._generation:
            process.deleteLater()
            return
        if key == "snapshot" and code == 0:
            try:
                parsed = json.loads(stdout)
                if isinstance(parsed, dict):
                    self.snapshotReady.emit(parsed)
                else:
                    self.error.emit("CLI snapshot returned JSON that was not an object.")
            except ValueError as exc:
                self.error.emit(f"Could not read CLI snapshot JSON: {exc}\n{stderr[-1200:]}")
        elif key == "snapshot" and code != 0:
            self.error.emit(f"CLI snapshot exited with code {code}:\n{(stderr or stdout)[-1600:]}")
        self.processFinished.emit(key, code, stdout, stderr)
        process.deleteLater()

    def _failed(self, key: str, process: QProcess, error: QProcess.ProcessError) -> None:
        # QProcess can emit FailedToStart and then finished; clear it here so a
        # visible Retry is immediately available.
        if error == QProcess.ProcessError.FailedToStart:
            message = process.errorString()
            if self._active.get(key) is process:
                self._active.pop(key, None)
            if int(process.property("profileGeneration") or 0) == self._generation:
                self.error.emit(f"Could not start {key}: {message}")
                self.processFinished.emit(key, -1, "", message)
            process.deleteLater()
