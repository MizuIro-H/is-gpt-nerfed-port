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


if __name__ == "__main__":
    unittest.main()
