"""Focused offline regression checks for cross-platform core launch paths."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugin/skills/is-gpt-nerfed/scripts/nerfed"
loader = importlib.machinery.SourceFileLoader("platform_core", str(SCRIPT))
spec = importlib.util.spec_from_loader("platform_core", loader)
core = importlib.util.module_from_spec(spec)
loader.exec_module(core)


class PlatformCoreTests(unittest.TestCase):
    def test_windows_codex_candidates_include_exe_and_npm_shim(self):
        if os.name != "nt":
            self.skipTest("Windows executable discovery")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            native, shim = root / "codex.exe", root / "codex.cmd"
            native.touch()
            shim.touch()
            with mock.patch.dict(os.environ, {"PATH": td + os.pathsep + td,
                                               "LOCALAPPDATA": td, "ProgramFiles": td}), \
                 mock.patch.object(core, "APP_CODEX_BINS", []), \
                 mock.patch.object(core.shutil, "which", return_value=None), \
                 mock.patch.object(core.glob, "glob", return_value=[]):
                self.assertEqual(core.codex_candidates(), [str(native), str(shim)])

    def test_sqlite_uri_escapes_special_path_characters(self):
        with tempfile.TemporaryDirectory(prefix="dgc db # ü ") as td:
            home = Path(td)
            db = home / "state_42.sqlite"
            con = sqlite3.connect(db)
            try:
                with con:
                    con.execute("create table probe (value text)")
                    con.execute("insert into probe values (?)", ("ok",))
            finally:
                con.close()
            with mock.patch.object(core, "CODEX_HOME", str(home)):
                self.assertEqual(core.db_query("select value from probe"), [{"value": "ok"}])

    def test_runtime_shell_launcher_preserves_argv_and_environment(self):
        if os.name == "nt":
            self.skipTest("runtime.sh is POSIX-only")
        with tempfile.TemporaryDirectory(prefix="dgc runtime ") as td:
            root = Path(td) / "plugin root's"
            root.mkdir()
            home = Path(td) / "state dir"
            fake = Path(td) / "fake core's"
            record = Path(td) / "argv.json"
            fake.write_text("#!/usr/bin/env python3\nimport json,os,sys\n"
                            "json.dump({'argv':sys.argv[1:],'root':os.environ['NERFED_PLUGIN_ROOT']},open(os.environ['RECORD'],'w'))\n",
                            encoding="utf-8")
            fake.chmod(0o700)
            with mock.patch.object(core, "NERFED_HOME", str(home)), mock.patch.dict(os.environ, {"RECORD": str(record)}):
                core.write_hook_runtime([str(fake), "arg with spaces", "quote'arg"], str(root))
            p = subprocess.run(["/bin/sh", str(home / "runtime.sh"), "event with space"],
                               capture_output=True, text=True, env=dict(os.environ, RECORD=str(record)))
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(record.read_text(encoding="utf-8")), {
                "argv": ["arg with spaces", "quote'arg", "event with space"], "root": str(root)})

    def test_detached_worker_args_for_source_and_frozen(self):
        args = Namespace(fresh=True, thread="thread/一", model="gpt-x", effort="high", queries=2)
        source = core.detached_worker_command(args, frozen=False)
        frozen = core.detached_worker_command(args, frozen=True)
        self.assertEqual(source, [sys.executable, str(SCRIPT), "worker", "--fresh", "--thread", "thread/一",
                                  "--model", "gpt-x", "--effort", "high", "--queries", "2"])
        self.assertEqual(frozen, [sys.executable, "worker", "--fresh", "--thread", "thread/一",
                                  "--model", "gpt-x", "--effort", "high", "--queries", "2"])

    def test_detached_environment_resets_frozen_bootloader_only(self):
        with mock.patch.dict(os.environ, {"CODEX_SANDBOX_NETWORK_DISABLED": "1"}, clear=False):
            source = core.child_process_env(strip_sandbox=True, frozen=False)
            frozen = core.child_process_env(strip_sandbox=True, frozen=True)
        self.assertNotIn("CODEX_SANDBOX_NETWORK_DISABLED", source)
        self.assertNotIn("PYINSTALLER_RESET_ENVIRONMENT", source)
        self.assertNotIn("CODEX_SANDBOX_NETWORK_DISABLED", frozen)
        self.assertEqual(frozen["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_core_reconfigures_redirected_stdio_as_utf8(self):
        class Stream:
            def __init__(self):
                self.settings = None
            def reconfigure(self, **kwargs):
                self.settings = kwargs

        streams = [Stream(), Stream(), Stream()]
        with mock.patch.object(core.sys, "stdin", streams[0]), \
             mock.patch.object(core.sys, "stdout", streams[1]), \
             mock.patch.object(core.sys, "stderr", streams[2]):
            core.configure_utf8_stdio()
        self.assertEqual([s.settings for s in streams],
                         [{"encoding": "utf-8", "errors": "replace"}] * 3)

    def test_posix_manifest_hook_fails_open_when_launcher_missing(self):
        if os.name == "nt":
            self.skipTest("POSIX manifest hook runs on POSIX")
        manifest = json.loads((ROOT / "plugin/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        command = manifest["hooks"]["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, PLUGIN_ROOT=str(Path(td) / "missing"), NERFED_HOME=str(Path(td) / "no-runtime"))
            p = subprocess.run(["/bin/sh", "-c", command], input="{}\n", text=True, env=env,
                               capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    @unittest.skipUnless(os.name == "nt", "native Windows hook validation")
    def test_windows_manifest_hook_fails_open_when_launcher_missing(self):
        manifest = json.loads((ROOT / "plugin/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        command = manifest["hooks"]["hooks"]["SessionStart"][0]["hooks"][0]["commandWindows"]
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, PLUGIN_ROOT=str(Path(td) / "missing"), NERFED_HOME=str(Path(td) / "no-runtime"))
            p = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command],
                               input="{}\n", text=True, env=env, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    @unittest.skipUnless(os.name == "nt", "native Windows execution-policy validation")
    def test_windows_hook_launcher_runs_under_restricted_parent_policy(self):
        manifest = json.loads((ROOT / "plugin/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        command = manifest["hooks"]["hooks"]["SessionStart"][0]["hooks"][0]["commandWindows"]
        self.assertIn("-ExecutionPolicy Bypass", command)
        with tempfile.TemporaryDirectory() as td:
            plugin = Path(td) / "plugin"
            hook = plugin / "skills/is-gpt-nerfed/scripts/hook.ps1"
            hook.parent.mkdir(parents=True)
            marker = Path(td) / "launcher-ran.txt"
            hook.write_text("param([string]$Event)\n$u=New-Object System.Text.UTF8Encoding($false)\n"
                            "[Console]::InputEncoding=$u\n$payload=[Console]::In.ReadToEnd()\n"
                            "[IO.File]::WriteAllText($env:HOOK_MARKER, \"$Event|$payload\", $u)\n",
                            encoding="utf-8-sig")
            env = dict(os.environ, PLUGIN_ROOT=str(plugin), HOOK_MARKER=str(marker),
                       NERFED_HOME=str(Path(td) / "empty"), PSExecutionPolicyPreference="Restricted")
            # Match Codex's Windows command runner: cmd /C receives the complete
            # command as raw text wrapped in quotes (not list2cmdline-escaped).
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            raw_commandline = f'"{comspec}" /C "{command}"'
            p = subprocess.run(raw_commandline, executable=comspec, input='{"unicode":"你好"}\n',
                               text=True, encoding="utf-8", capture_output=True, timeout=20, env=env)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), 'SessionStart|{"unicode":"你好"}\n')

    def test_write_json_retries_transient_permission_error_and_cleans_tmp(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "state.json"
            real_replace = core.os.replace
            calls = {"count": 0}

            def flaky_replace(src, dst):
                calls["count"] += 1
                if calls["count"] < 3:
                    raise PermissionError(13, "locked")
                return real_replace(src, dst)

            with mock.patch.object(core.os, "name", "nt"), \
                 mock.patch.object(core.os, "replace", side_effect=flaky_replace), \
                 mock.patch.object(core.time, "sleep"):
                core.write_json(str(target), {"ok": True})
            self.assertEqual(calls["count"], 3)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True})
            self.assertEqual(list(Path(td).glob("*.tmp")), [])

            with mock.patch.object(core.os, "name", "nt"), \
                 mock.patch.object(core.os, "replace", side_effect=PermissionError(13, "still locked")), \
                 mock.patch.object(core.time, "sleep"):
                with self.assertRaises(PermissionError):
                    core.write_json(str(target), {"ok": False})
            self.assertEqual(list(Path(td).glob("*.tmp")), [])

    def test_log_event_and_error_write_valid_lines(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "log.jsonl"
            err_path = Path(td) / "errors.log"
            with mock.patch.object(core, "NERFED_HOME", td), \
                 mock.patch.object(core, "LOG_PATH", str(log_path)), \
                 mock.patch.object(core, "ERRORS_PATH", str(err_path)):
                core.log_event("test_kind", count=1, note="你好")
                core.log_error("boom")
            rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["kind"], "test_kind")
            self.assertEqual(rows[0]["note"], "你好")
            self.assertEqual(rows[1]["kind"], "error")
            self.assertEqual(rows[1]["level"], "error")
            self.assertIn("boom", err_path.read_text(encoding="utf-8"))

    def test_default_originator_recognizes_windows_desktop_codex(self):
        self.assertEqual(
            core.default_originator(r"C:\Program Files\WindowsApps\OpenAI.Codex_26.1111.2228.0_x64__2p2nqsd0c76g0\app\resources\codex.exe"),
            "Codex Desktop",
        )
        self.assertEqual(
            core.default_originator(r"C:\Users\u\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe"),
            "Codex Desktop",
        )
        self.assertEqual(
            core.default_originator(r"C:\Users\u\AppData\Roaming\npm\codex.cmd"),
            "codex_cli_rs",
        )

    def test_windows_detached_options_avoid_blank_console_window(self):
        if os.name != "nt":
            self.skipTest("Windows subprocess window flags")
        detached = core.popen_detached_options()
        self.assertTrue(detached["creationflags"] & subprocess.CREATE_NO_WINDOW)
        self.assertFalse(detached["creationflags"] & subprocess.DETACHED_PROCESS)
        self.assertTrue(detached["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(detached["close_fds"])
        self.assertTrue(detached["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(detached["startupinfo"].wShowWindow, subprocess.SW_HIDE)

        window_opts = core.subprocess_window_kwargs()
        self.assertTrue(window_opts["creationflags"] & subprocess.CREATE_NO_WINDOW)
        self.assertTrue(window_opts["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(window_opts["startupinfo"].wShowWindow, subprocess.SW_HIDE)


if __name__ == "__main__":
    unittest.main()
