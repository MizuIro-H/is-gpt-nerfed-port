"""Offline, isolated checks for the Qt desktop/backend boundary.

Run with `python -m unittest discover -s tests -p test_desktop.py -v`.
PySide6 is optional for the CLI-only test environment; these checks skip cleanly
when the desktop dependency is not installed.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QByteArray, QProcess, QStandardPaths
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QWidget
    import desktop.backend as backend_module
    import desktop.main as main_module
    from desktop.backend import Backend, ProfileStore
    from desktop.main import MainWindow, SettingsDialog
    from desktop.winui_bridge import WinUIInspector
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 is required for desktop checks")
class DesktopBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setApplicationName("is-gpt-nerfed-tests")
        cls.app.setOrganizationName("is-gpt-nerfed-tests")
        QStandardPaths.setTestModeEnabled(True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.app.quit()

    def make_config(self) -> dict:
        return {
            "frequency": "30m", "fresh_frequency": "manual", "mode": "nudge",
            "queries": 3, "mismatch_confidence": 0.8, "parallel": True,
            "passive": True, "notify": True, "notify_on_ok": False,
            "announce_ok": False, "sound": True, "halt_on_mismatch": False,
            "hide_titles": False,
        }

    def make_dialog(self, config: dict, backend: Backend | None = None):
        backend = backend or Backend(demo=True)
        if backend._temp:
            self.addCleanup(backend._temp.cleanup)
        # Keep the test independent from a host WSL installation.
        backend.discover_distros = lambda: None
        parent = QWidget()
        parent.snapshot_data = {"config": config}
        with mock.patch.object(main_module, "_autostart_enabled", return_value=False):
            dialog = SettingsDialog(backend, parent)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(parent.deleteLater)
        return dialog, backend

    def test_valid_nudge_defaults_save_with_no_config_delta(self) -> None:
        dialog, _ = self.make_dialog(self.make_config())
        self.assertEqual(dialog.mode.currentText(), "nudge")
        self.assertEqual(dialog.frequency.currentText(), "30m")
        self.assertEqual(dialog.queries.value(), 3)
        self.assertAlmostEqual(dialog.confidence.value(), 0.8)
        self.assertEqual(dialog.config_updates(), [])

    def test_multiple_config_changes_keep_stable_set_order(self) -> None:
        dialog, _ = self.make_dialog(self.make_config())
        dialog.queries.setValue(2)
        dialog.config_boxes["notify_on_ok"].setChecked(True)
        self.assertEqual(dialog.config_updates(), [("queries", "2"), ("notify_on_ok", "true")])

    def test_demo_settings_are_read_only_and_do_not_save_profiles(self) -> None:
        dialog, backend = self.make_dialog(self.make_config())
        save = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save)
        self.assertFalse(save.isEnabled())
        self.assertFalse(dialog.autostart.isEnabled())
        self.assertFalse(dialog.config_boxes["notify"].isEnabled())
        original = dict(backend.profile)
        backend.profile_store.save = mock.Mock(side_effect=AssertionError("demo must not write profile JSON"))
        backend.save_profile({"kind": "wsl", "distro": "test", "codex_home": "", "codex_bin": ""})
        self.assertNotEqual(backend.profile, original)  # only its in-memory demo profile changes
        backend.profile_store.save.assert_not_called()
        self.assertTrue(str(backend._demo_root).startswith(tempfile.gettempdir()))

    def test_windows_defaults_to_native_and_unc_autoselects_owning_wsl(self) -> None:
        old_platform = sys.platform
        old_home = os.environ.get("CODEX_HOME")
        try:
            sys.platform = "win32"
            os.environ["CODEX_HOME"] = r"C:\Users\sample\.codex"
            self.assertEqual(ProfileStore(create=False).load()["kind"], "native")
            os.environ["CODEX_HOME"] = r"\\WSL.LOCALHOST\4AgentHarness\home\sample\.codex"
            profile = ProfileStore(create=False).load()
            self.assertEqual(profile["kind"], "wsl")
            self.assertEqual(profile["distro"], "4AgentHarness")
            self.assertEqual(profile["codex_home"], "")
        finally:
            sys.platform = old_platform
            if old_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = old_home

    def test_windows_demo_ignores_host_wsl_unc_but_native_profile_still_rejects_it(self) -> None:
        backend = Backend(demo=True)
        self.addCleanup(backend._temp.cleanup)
        old_platform, old_executable = sys.platform, sys.executable
        old_home = os.environ.get("CODEX_HOME")
        was_frozen = getattr(sys, "frozen", None)
        try:
            sys.platform = "win32"
            sys.executable = str(Path(tempfile.gettempdir()) / "IsGPTNerfed.exe")
            sys.frozen = True
            os.environ["CODEX_HOME"] = r"\\wsl.localhost\4AgentHarness\home\sample\.codex"
            with mock.patch.object(backend_module.shutil, "which", return_value=None):
                program, argv, _ = backend._command(["snapshot", "--demo", "--json"])
            # Windows TEMP may use an 8.3 alias for the same directory.
            self.assertEqual(Path(program).resolve(), (Path(tempfile.gettempdir()) / "nerfed-core.exe").resolve())
            self.assertEqual(argv, ["snapshot", "--demo", "--json"])

            backend.demo = False
            with self.assertRaisesRegex(RuntimeError, "belongs to WSL"):
                backend._command(["snapshot", "--json"])
        finally:
            sys.platform, sys.executable = old_platform, old_executable
            if was_frozen is None:
                del sys.frozen
            else:
                sys.frozen = was_frozen
            if old_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = old_home

    def test_profile_switch_waits_for_worker_and_does_not_apply_old_config(self) -> None:
        backend = Backend(demo=True)
        self.addCleanup(backend._temp.cleanup)
        backend.demo = False
        backend.profile_store.save = mock.Mock()
        target = {"kind": "wsl", "distro": "Ubuntu", "codex_home": "", "codex_bin": ""}
        backend._active["probe:thread-1"] = object()
        self.assertFalse(backend.save_profile(target))
        backend._active.clear()
        self.assertTrue(backend.save_profile(target))
        self.assertEqual(backend.profile, target)
        self.assertEqual(backend._generation, 1)
        backend.profile_store.save.assert_called_once_with(target)

    def test_frozen_wsl_command_expands_linux_home_and_quotes_payload_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nerfed wsl ") as temp:
            package = Path(temp)
            exe = package / "IsGPTNerfed.exe"
            exe.touch()
            archive = package / "release's core.tar.gz"
            archive.write_bytes(b"test-only archive marker")
            backend = Backend(demo=True)
            self.addCleanup(backend._temp.cleanup)
            backend.profile = {"kind": "wsl", "distro": "4AgentHarness", "codex_home": "", "codex_bin": ""}
            backend._archive_path = lambda: archive

            old_platform, old_executable = sys.platform, sys.executable
            was_frozen = getattr(sys, "frozen", None)
            try:
                sys.platform = "win32"
                sys.executable = str(exe)
                sys.frozen = True
                with mock.patch.object(backend_module.shutil, "which", return_value=None):
                    program, argv, _ = backend._command(["snapshot", "--json"])
            finally:
                sys.platform, sys.executable = old_platform, old_executable
                if was_frozen is None:
                    del sys.frozen
                else:
                    sys.frozen = was_frozen

            shell = argv[-1]
            self.assertEqual(program, "wsl.exe")
            self.assertEqual(argv[:4], ["-d", "4AgentHarness", "--exec", "sh"])
            self.assertIn('dest="$HOME/.local/share/is-gpt-nerfed/runtime/0.5.3-crossplatform"', shell)
            self.assertIn('NERFED_PLUGIN_ROOT="$dest/plugin"', shell)
            self.assertIn('NERFED_CORE_BIN="$dest/nerfed-core"', shell)
            self.assertNotIn("'$HOME", shell)
            self.assertIn(__import__("shlex").quote(str(archive)), shell)
            self.assertIn('env -u CODEX_HOME -u NERFED_HOME', shell)

    def test_winui_startup_crash_falls_back_to_qt_and_clears_pending(self):
        win = QWidget()
        self.addCleanup(win.deleteLater)
        win._show_error = mock.Mock()
        win._open_qt_inspector = mock.Mock()
        bridge = WinUIInspector(win, Path("IsGPTNerfed.Inspector.exe"), lambda en, _zh: en, Path("icon.png"),
                                fallback=win._open_qt_inspector)
        bridge._pending_show = ["thread-123"]
        fake_proc = mock.Mock()
        fake_proc.exitCode.return_value = 1
        fake_proc.readAllStandardError.return_value = QByteArray(b"System.Exception: boom\n")
        bridge.proc = fake_proc
        bridge._exited()
        self.assertEqual(bridge._pending_show, [])
        win._show_error.assert_called_once()
        self.assertIn("boom", win._show_error.call_args.args[0])
        win._open_qt_inspector.assert_called_once_with("thread-123")

    def test_winui_buffers_logs_until_ready(self):
        win = QWidget()
        self.addCleanup(win.deleteLater)
        win.snapshot_data = None
        win.demo = False
        win.backend = Backend(demo=True)
        self.addCleanup(win.backend._temp.cleanup)
        win.pending_probes = {}
        win.pending_fresh_at = None
        win._target_text = lambda: "Native"
        win._status_word = lambda s: s
        bridge = WinUIInspector(win, Path("IsGPTNerfed.Inspector.exe"), lambda en, _zh: en, Path("icon.png"))
        sent = []
        bridge._send = sent.append
        bridge.log("line-1")
        bridge.log("line-2")
        self.assertEqual(sent, [])
        bridge._pending_show = ["t-1"]
        bridge._handle({"action": "ready"})
        self.assertEqual(bridge._pending_logs, [])
        self.assertEqual(bridge._pending_show, [])
        self.assertEqual([m["type"] for m in sent], ["init", "state", "log", "log", "show", "state"])
        self.assertEqual([m["text"] for m in sent if m["type"] == "log"], ["line-1", "line-2"])
        self.assertEqual(sent[-2]["thread"], "t-1")

    def test_settings_dialog_prevents_reentrancy(self):
        backend = Backend(demo=True)
        self.addCleanup(backend._temp.cleanup)
        existing = mock.Mock()
        fake_win = type("FakeWin", (), {
            "_settings_dialog": existing,
            "backend": backend,
            "snapshot_data": {"config": self.make_config()},
            "pending_probes": {},
            "pending_fresh_at": None,
            "demo": False,
        })()
        with mock.patch.object(main_module, "SettingsDialog") as dialog_cls:
            MainWindow.settings(fake_win)
        existing.raise_.assert_called_once()
        existing.activateWindow.assert_called_once()
        dialog_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
