"""Qt Widgets desktop inspector for is-gpt-nerfed."""
from __future__ import annotations

import json
import os
import shlex
import sys
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QLocale, QTimer, QStandardPaths
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QPlainTextEdit, QSplitter, QSystemTrayIcon, QTabWidget, QTableWidget, QSpinBox, QDoubleSpinBox,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtWidgets import QHeaderView, QMenu
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtCore import QUrl

try:
    from .backend import Backend
except ImportError:
    from backend import Backend


ZH = QLocale.system().name().lower().startswith("zh")


def tr(en: str, zh: str) -> str:
    return zh if ZH else en


class SettingsDialog(QDialog):
    def __init__(self, backend: Backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.setWindowTitle(tr("Settings", "设置"))
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        self.target = QComboBox()
        self.target.addItem(tr("Native (this OS)", "本机（当前系统）"), "native")
        if sys.platform == "win32":
            self.target.addItem("WSL 2", "wsl")
        self.distro = QComboBox()
        self.distro.setEditable(True)
        self.home = QLineEdit()
        self.home.setPlaceholderText(tr("Leave blank to use the target's default Codex home", "留空则使用目标系统的默认 Codex home"))
        self.binary = QLineEdit()
        self.binary.setPlaceholderText(tr("Leave blank to find Codex automatically", "留空则自动查找 Codex"))
        self.autostart = QCheckBox(tr("Start at sign-in (off by default)", "登录时启动（默认关闭）"))
        self.autostart.setChecked(_autostart_enabled())
        self._autostart_initial = self.autostart.isChecked()
        form.addRow(tr("Run core in", "核心运行于"), self.target)
        form.addRow(tr("WSL distribution", "WSL 发行版"), self.distro)
        form.addRow(tr("Codex home override", "Codex home 覆盖路径"), self.home)
        form.addRow(tr("Codex executable", "Codex 可执行文件"), self.binary)
        form.addRow("", self.autostart)
        self.status = QLabel(tr("Profiles are saved per user. WSL uses that distro's own Linux home.",
                                 "配置保存在当前用户目录。WSL 使用对应发行版自己的 Linux home。"))
        self.status.setWordWrap(True)
        form.addRow(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        profile = backend.profile
        self.target.setCurrentIndex(max(0, self.target.findData(profile.get("kind", "native"))))
        self.distro.setEditText(profile.get("distro", ""))
        self.home.setText(profile.get("codex_home", ""))
        self.binary.setText(profile.get("codex_bin", ""))
        cfg = (getattr(parent, "snapshot_data", None) or {}).get("config") or {}
        self._initial_config = dict(cfg)
        self.frequency = QComboBox(); self.frequency.setEditable(True)
        self.frequency.addItems(["30m", "1h", "2h", "4h", "turns:8", "turns:16", "manual"])
        self.frequency.setCurrentText(str(cfg.get("frequency", "30m")))
        self.fresh_frequency = QComboBox(); self.fresh_frequency.setEditable(True)
        self.fresh_frequency.addItems(["manual", "30m", "1h", "2h", "6h", "24h"])
        self.fresh_frequency.setCurrentText(str(cfg.get("fresh_frequency", "manual")))
        self.mode = QComboBox(); self.mode.addItems(["auto", "nudge"])
        self.mode.setCurrentText(str(cfg.get("mode", "auto")))
        self.queries = QSpinBox(); self.queries.setRange(1, 3); self.queries.setValue(int(cfg.get("queries", 3)))
        self.confidence = QDoubleSpinBox(); self.confidence.setRange(0.5, 0.99); self.confidence.setSingleStep(0.01)
        self.confidence.setValue(float(cfg.get("mismatch_confidence", 0.8)))
        form.addRow(tr("Probe schedule", "探测频率"), self.frequency)
        form.addRow(tr("Fresh probe schedule", "全新探测频率"), self.fresh_frequency)
        form.addRow(tr("Probe mode", "探测模式"), self.mode)
        form.addRow(tr("Query count", "探测次数"), self.queries)
        form.addRow(tr("Mismatch confidence", "不匹配置信度"), self.confidence)
        self.config_boxes: dict[str, QCheckBox] = {}
        for key, label in [("parallel", tr("Run probes in parallel", "并行探测")),
                            ("passive", tr("Scan passive evidence", "扫描被动证据")),
                            ("notify", tr("Desktop notifications", "桌面通知")),
                            ("notify_on_ok", tr("Notify on matching results", "匹配时也通知")),
                            ("announce_ok", tr("Announce matching results", "播报匹配结果")),
                            ("sound", tr("Play alert sound", "播放警告声音")),
                            ("halt_on_mismatch", tr("Halt sessions on mismatch", "不匹配时暂停会话")),
                            ("hide_titles", tr("Hide session titles", "隐藏会话标题"))]:
            box = QCheckBox(label); box.setChecked(bool(cfg.get(key, key in ("passive", "notify", "sound"))))
            self.config_boxes[key] = box
            form.addRow("", box)
        self.target.currentIndexChanged.connect(self._target_changed)
        self._target_changed()
        self._config_ready = bool(cfg)
        if not self._config_ready:
            for widget in (self.frequency, self.fresh_frequency, self.mode, self.queries, self.confidence, *self.config_boxes.values()):
                widget.setEnabled(False)
            self.status.setText(tr("Core settings appear after the first successful snapshot.", "首次成功读取状态后即可编辑核心设置。"))
        if backend.demo:
            for widget in (self.target, self.distro, self.home, self.binary, self.autostart,
                           self.frequency, self.fresh_frequency, self.mode, self.queries,
                           self.confidence, *self.config_boxes.values()):
                widget.setEnabled(False)
            save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
            if save_button:
                save_button.setEnabled(False)
            self.status.setText(tr("Demo settings are read-only; no profile or startup changes will be saved.",
                                   "演示模式设置为只读，不会保存配置或自启动更改。"))
        form.addRow(buttons)
        backend.distrosReady.connect(self._set_distros)
        backend.discover_distros()

    def _target_changed(self) -> None:
        self.distro.setEnabled(self.target.currentData() == "wsl")

    def _set_distros(self, values: list) -> None:
        old = self.distro.currentText()
        self.distro.clear()
        self.distro.addItems(values)
        self.distro.setEditText(old)
        if not values and sys.platform == "win32":
            self.status.setText(tr("Could not list WSL distributions. Enter an installed distribution name.",
                                   "无法读取 WSL 发行版列表。请手动输入已安装的发行版名称。"))

    def profile(self) -> dict:
        return {"kind": self.target.currentData(), "distro": self.distro.currentText().strip(),
                "codex_home": self.home.text().strip(), "codex_bin": self.binary.text().strip()}

    def config_updates(self) -> list[tuple[str, str]]:
        if not self._config_ready:
            return []
        values = {"frequency": self.frequency.currentText().strip(),
                  "fresh_frequency": self.fresh_frequency.currentText().strip(),
                  "mode": self.mode.currentText(), "queries": str(self.queries.value()),
                  "mismatch_confidence": str(self.confidence.value())}
        values.update({key: "true" if box.isChecked() else "false" for key, box in self.config_boxes.items()})
        updates: list[tuple[str, str]] = []
        bool_keys = set(self.config_boxes)
        for key, value in values.items():
            old = self._initial_config.get(key)
            if key in bool_keys:
                old = "true" if bool(old) else "false"
            elif old is not None:
                old = str(float(old)) if key == "mismatch_confidence" else str(old)
            if value != old:
                updates.append((key, value))
        return updates

    def autostart_enabled(self) -> bool:
        return self.autostart.isChecked()

    def autostart_changed(self) -> bool:
        return self.autostart.isChecked() != self._autostart_initial


def _autostart_enabled() -> bool:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, "is-gpt-nerfed")
                return True
        except OSError:
            return False
    path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)) / "autostart" / "is-gpt-nerfed.desktop"
    return path.is_file()


def _set_autostart(enabled: bool) -> None:
    if sys.platform == "win32":
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                if getattr(sys, "frozen", False):
                    command = subprocess.list2cmdline([sys.executable])
                else:
                    command = subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve().parent / "cli_entry.py")])
                winreg.SetValueEx(key, "is-gpt-nerfed", 0, winreg.REG_SZ, command)
            else:
                try: winreg.DeleteValue(key, "is-gpt-nerfed")
                except FileNotFoundError: pass
        return
    path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)) / "autostart" / "is-gpt-nerfed.desktop"
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        if getattr(sys, "frozen", False):
            command = '"' + str(Path(sys.executable).resolve()).replace('"', '\\"') + '"'
        else:
            py = '"' + str(Path(sys.executable).resolve()).replace('"', '\\"') + '"'
            entry = '"' + str((Path(__file__).resolve().parent / "cli_entry.py")).replace('"', '\\"') + '"'
            command = py + " " + entry
        path.write_text("[Desktop Entry]\nType=Application\nName=is-gpt-nerfed\nExec=" + command + "\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")
    else:
        try: path.unlink()
        except FileNotFoundError: pass


class MainWindow(QMainWindow):
    def __init__(self, backend: Backend, app: QApplication) -> None:
        super().__init__()
        self.backend = backend
        self.app = app
        self.demo = backend.demo
        self.snapshot_data: dict | None = None
        self.last_snapshot_error = ""
        self.seen_probe_ids: set[str] | None = None
        self.seen_evidence_ids: set[tuple[str, str, str]] | None = None
        self.selected_id = ""
        self.pending_probes: dict[str, float] = {}
        self.pending_fresh_at: float | None = None
        self.last_fresh_heartbeat = 0.0
        self._config_queue: list[tuple[str, str]] = []
        self._closing = False
        self.setWindowTitle(tr("is-gpt-nerfed", "is-gpt-nerfed"))
        self.resize(1020, 700)
        self._build_ui()
        self._build_tray()
        backend.snapshotReady.connect(self._snapshot_ready)
        backend.processFinished.connect(self._process_finished)
        backend.processStarted.connect(self._process_started)
        backend.error.connect(self._show_error)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(8000)
        self.poll_timer.timeout.connect(self.refresh)
        self.poll_timer.start()
        self.tick_timer = QTimer(self)
        self.tick_timer.setInterval(60000)
        self.tick_timer.timeout.connect(self._scheduler_tick)
        self.tick_timer.start()
        QTimer.singleShot(0, self.refresh)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        heading = QHBoxLayout()
        self.status_label = QLabel(tr("Connecting…", "正在连接…"))
        self.status_label.setStyleSheet("font-size: 19px; font-weight: 600")
        self.status_label.setMaximumWidth(530)
        heading.addWidget(self.status_label, 1)
        self.refresh_button = QPushButton(tr("Refresh", "刷新"))
        self.refresh_button.clicked.connect(self.refresh)
        self.settings_button = QPushButton(tr("Settings", "设置"))
        self.settings_button.clicked.connect(self.settings)
        self.exit_button = QPushButton(tr("Exit", "退出"))
        self.exit_button.clicked.connect(self.explicit_exit)
        heading.addWidget(self.refresh_button)
        heading.addWidget(self.settings_button)
        heading.addWidget(self.exit_button)
        root.addLayout(heading)
        self.substatus = QLabel(tr("Waiting for local snapshot…", "等待本地状态…"))
        self.substatus.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.substatus)

        self.tabs = QTabWidget()
        sessions_page = QWidget()
        sessions_layout = QVBoxLayout(sessions_page)
        self.thread_table = QTableWidget(0, 5)
        self.thread_table.setHorizontalHeaderLabels([
            tr("Session", "会话"), tr("Model", "模型"), tr("Effort", "推理强度"),
            tr("State", "状态"), tr("Evidence", "证据"),
        ])
        self.thread_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.thread_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.thread_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.thread_table.horizontalHeader().setStretchLastSection(True)
        self.thread_table.setWordWrap(False)
        for col, width in enumerate((240, 140, 80, 110)):
            self.thread_table.setColumnWidth(col, width)
        self.thread_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.thread_table.itemSelectionChanged.connect(self._selection_changed)
        sessions_layout.addWidget(self.thread_table, 3)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText(tr("Select a session to inspect its report and evidence history.",
                                          "选择会话以查看报告和证据历史。"))
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setPlaceholderText(tr("Probe history", "探测历史"))
        split.addWidget(self.report)
        split.addWidget(self.history)
        sessions_layout.addWidget(split, 2)
        actions = QHBoxLayout()
        self.probe_button = QPushButton(tr("Probe selected session", "探测所选会话"))
        self.probe_button.clicked.connect(self.probe_selected)
        self.retry_button = QPushButton(tr("Retry failed probe", "重试失败探测"))
        self.retry_button.clicked.connect(self.retry_selected)
        self.resume_button = QPushButton(tr("Resume halted session", "恢复已暂停会话"))
        self.resume_button.clicked.connect(self.resume_selected)
        self.copy_button = QPushButton(tr("Copy report", "复制报告"))
        self.copy_button.clicked.connect(self.copy_report)
        for button in (self.probe_button, self.retry_button, self.resume_button, self.copy_button):
            actions.addWidget(button)
        actions.addStretch(1)
        sessions_layout.addLayout(actions)
        self.tabs.addTab(sessions_page, tr("Sessions", "会话"))

        global_page = QWidget()
        global_layout = QVBoxLayout(global_page)
        global_layout.addWidget(QLabel(tr("Fresh session probe uses the configured default model and effort.",
                                          "全新会话探测使用配置的默认模型与推理强度。")))
        row = QHBoxLayout()
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText(tr("Default model (optional)", "默认模型（可选）"))
        self.effort_input = QComboBox()
        self.effort_input.setEditable(True)
        self.effort_input.addItems(["", "minimal", "low", "medium", "high", "xhigh", "max"])
        self.fresh_button = QPushButton(tr("Probe fresh session", "探测全新会话"))
        self.fresh_button.clicked.connect(self.probe_fresh)
        row.addWidget(self.model_input, 2)
        row.addWidget(self.effort_input, 1)
        row.addWidget(self.fresh_button)
        global_layout.addLayout(row)
        self.global_report = QPlainTextEdit()
        self.global_report.setReadOnly(True)
        global_layout.addWidget(self.global_report)
        self.tabs.addTab(global_page, tr("Fresh probe", "全新探测"))

        setup_page = QWidget()
        setup_layout = QVBoxLayout(setup_page)
        setup_layout.addWidget(QLabel(tr("Plugin installation and hook trust only run after you press a button.",
                                         "只有点击按钮后才会安装插件或信任 hooks。")))
        self.install_button = QPushButton(tr("Install plugin", "安装插件"))
        self.install_button.clicked.connect(self.install_plugin)
        self.trust_button = QPushButton(tr("Trust hooks", "信任 hooks"))
        self.trust_button.clicked.connect(self.trust_hooks)
        self.setup_status = QPlainTextEdit()
        self.setup_status.setReadOnly(True)
        setup_layout.addWidget(self.install_button)
        setup_layout.addWidget(self.trust_button)
        setup_layout.addWidget(self.setup_status)
        self.tabs.addTab(setup_page, tr("Plugin", "插件"))
        root.addWidget(self.tabs, 1)
        if self.demo:
            notice = QLabel(tr("DEMO MODE · offline sample data · no Codex home or model calls",
                               "演示模式 · 离线样例 · 不读取 Codex home，也不会请求模型"))
            notice.setStyleSheet("color: #805600; font-weight: 700; background: #fff4cc; padding: 7px")
            root.insertWidget(0, notice)
            for button in (self.probe_button, self.retry_button, self.resume_button, self.fresh_button,
                           self.install_button, self.trust_button):
                button.setEnabled(False)
            self.settings_button.setEnabled(False)
        self.setCentralWidget(central)

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self._icon_for("ok"))
        self.tray.setToolTip("is-gpt-nerfed")
        menu = self.tray.contextMenu() or QMenu()
        show = QAction(tr("Open panel", "打开面板"), self)
        show.triggered.connect(self.showNormal)
        refresh = QAction(tr("Refresh", "刷新"), self)
        refresh.triggered.connect(self.refresh)
        exit_action = QAction(tr("Exit", "退出"), self)
        exit_action.triggered.connect(self.explicit_exit)
        menu.addAction(show)
        menu.addAction(refresh)
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    @staticmethod
    def _icon_for(status: str) -> QIcon:
        colors = {"alert": QColor("#c62828"), "warn": QColor("#ed8b00"),
                  "ok": QColor("#2e7d32"), "upgraded": QColor("#2e7d32"),
                  "unverified": QColor("#607d8b")}
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(colors.get(status, QColor("#546e7a")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 56, 56)
        painter.setPen(QColor("white"))
        font = painter.font(); font.setBold(True); font.setPointSize(32); painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "!" if status in ("alert", "warn") else "✓")
        painter.end()
        return QIcon(pix)

    def refresh(self) -> None:
        if "snapshot" not in self.backend.busy:
            self.backend.snapshot()

    def _snapshot_ready(self, snap: dict) -> None:
        self.snapshot_data = snap
        self.last_snapshot_error = ""
        overall = snap.get("overall") or {}
        state = str(overall.get("status", "unknown"))
        message = str(overall.get("message", ""))
        color = {"alert": "#b42318", "warn": "#b54708", "ok": "#18794e", "upgraded": "#18794e"}.get(state, "#444")
        self.status_label.setText(f"{self._status_word(state)} · {message}")
        self.status_label.setToolTip(message)
        self.status_label.setStyleSheet(f"font-size: 19px; font-weight: 600; color: {color}")
        if self.tray:
            self.tray.setIcon(self._icon_for(state))
            self.tray.setToolTip("is-gpt-nerfed · " + message)
        generated = snap.get("generated", "")
        self.substatus.setText(tr(f"Updated {generated} · {self._target_text()}", f"更新于 {generated} · {self._target_text()}"))
        self._populate_threads(snap.get("threads") or [])
        self.fresh_button.setEnabled(not self.demo and not snap.get("global_running")
                                     and not self.pending_fresh_at and "fresh" not in self.backend.busy)
        import time
        now = time.time()
        by_id = {t.get("id"): t for t in snap.get("threads") or []}
        for tid, started in list(self.pending_probes.items()):
            thread = by_id.get(tid)
            finished = (thread or {}).get("last_probe", {}).get("finished") or (thread or {}).get("last_failure", {}).get("finished")
            if now - started > 180 or (finished and self._iso_time(finished) >= started):
                self.pending_probes.pop(tid, None)
        fresh = snap.get("global_probe") or {}
        failure = snap.get("global_failure") or {}
        finished = fresh.get("finished") or failure.get("finished")
        if self.pending_fresh_at and (now - self.pending_fresh_at > 180 or (finished and self._iso_time(finished) >= self.pending_fresh_at)):
            self.pending_fresh_at = None
            self.fresh_button.setEnabled(not self.demo)
        self.global_report.setPlainText(str(snap.get("global_report_text") or ""))
        self._show_plugin_status(snap)
        self._notify_new_probes(snap)

    def _populate_threads(self, threads: list[dict]) -> None:
        current = self.selected_id
        self.thread_table.setRowCount(len(threads))
        for i, thread in enumerate(threads):
            state = self._thread_state(thread)
            evidence = thread.get("last_evidence") or ""
            values = [thread.get("title") or thread.get("id", ""), thread.get("model") or "—",
                      thread.get("effort") or "—", state, evidence]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, thread.get("id"))
                if col == 0:
                    item.setToolTip(str(thread.get("title") or ""))
                elif col == 4:
                    item.setToolTip(str(evidence))
                if col == 0 and thread.get("alert"):
                    item.setForeground(Qt.GlobalColor.red)
                self.thread_table.setItem(i, col, item)
            self.thread_table.setRowHeight(i, 30)
            if thread.get("id") == current:
                self.thread_table.selectRow(i)
        if not current and threads:
            self.thread_table.selectRow(0)
        self._selection_changed()

    def _selection_changed(self) -> None:
        thread = self._selected_thread()
        if not thread:
            self.selected_id = ""
            self.report.clear()
            self.history.clear()
            self.probe_button.setEnabled(False)
            self.retry_button.setEnabled(False)
            self.resume_button.setEnabled(False)
            return
        self.selected_id = thread.get("id", "")
        self.report.setPlainText(str(thread.get("report_text") or ""))
        lines = []
        for item in thread.get("evidence") or []:
            active = "active" if item.get("active", True) else "reverted"
            lines.append(f"[{item.get('severity') or 'evidence'} · {active} · {item.get('ago') or item.get('ts') or ''}] {item.get('text', '')}")
        if lines:
            lines.append("")
        for probe in thread.get("probes") or []:
            lines.append(self._probe_line(probe))
        failure = thread.get("last_failure")
        if failure:
            lines.insert(0, tr("Latest failed attempt: ", "最近失败尝试：") + self._probe_line(failure))
        self.history.setPlainText("\n".join(lines))
        busy = "probe:" + self.selected_id in self.backend.busy or self.selected_id in self.pending_probes
        self.probe_button.setEnabled(not self.demo and not busy and not thread.get("probe_running"))
        self.retry_button.setEnabled(not self.demo and not busy and bool(failure and failure.get("retryable")))
        self.resume_button.setEnabled(not self.demo and bool(thread.get("halted")))

    def _selected_thread(self) -> dict | None:
        if not self.snapshot_data:
            return None
        row = self.thread_table.currentRow()
        if row < 0 or row >= self.thread_table.rowCount():
            return None
        item = self.thread_table.item(row, 0)
        thread_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((x for x in self.snapshot_data.get("threads", []) if x.get("id") == thread_id), None)

    def _process_started(self, key: str) -> None:
        if key != "snapshot":
            self.setup_status.appendPlainText(f"{key}: {tr('started', '已启动')}")
        self._selection_changed()

    def _process_finished(self, key: str, code: int, stdout: str, stderr: str) -> None:
        if code != 0 and key == "fresh":
            self.pending_fresh_at = None
            self.fresh_button.setEnabled(not self.demo)
        elif code != 0 and key.startswith("probe:"):
            self.pending_probes.pop(key[len("probe:"):], None)
        if key != "snapshot":
            tail = (stdout or stderr).strip()[-6000:]
            self.setup_status.appendPlainText(f"{key}: {tr('finished', '已结束')} ({code})\n{tail or tr('(no output)', '（无输出）')}")
            if code != 0:
                self._show_error(f"{key} exited with code {code}:\n{(stderr or stdout).strip()[-2000:]}")
            if key.startswith("config:"):
                if code == 0:
                    self._start_next_config()
                else:
                    self._config_queue.clear()
        self._selection_changed()

    def _show_error(self, message: str) -> None:
        self.last_snapshot_error = message
        self.substatus.setText(tr("Operation error: ", "操作错误：") + message)
        if self.tray:
            self.tray.showMessage("is-gpt-nerfed", message[:800], QSystemTrayIcon.MessageIcon.Warning, 8000)

    def _notify_new_probes(self, snap: dict) -> None:
        if self.demo:
            return
        cfg = snap.get("config") or {}
        probes = []
        evidence: dict[tuple[str, str, str], str] = {}
        for thread in snap.get("threads") or []:
            probes.extend(thread.get("probes") or [])
            for finding in thread.get("evidence") or []:
                if finding.get("severity") == "hard" and finding.get("active", True):
                    identity = (str(thread.get("id") or ""), str(finding.get("ts") or ""), str(finding.get("text") or ""))
                    evidence[identity] = str(thread.get("title") or thread.get("id") or "Session") + " · " + identity[2]
        probes.extend(snap.get("global_probes") or [])
        known = {str(p.get("id")): p for p in probes if p.get("id")}
        if self.seen_probe_ids is None or self.seen_evidence_ids is None:
            # Establish a baseline on first successful poll: old evidence must not
            # generate a delayed notification just because the panel was opened.
            self.seen_probe_ids = set(known)
            self.seen_evidence_ids = set(evidence)
            return
        new = [p for pid, p in known.items() if pid not in self.seen_probe_ids]
        self.seen_probe_ids.update(known)
        new_evidence = [message for identity, message in evidence.items() if identity not in self.seen_evidence_ids]
        self.seen_evidence_ids.update(evidence)
        if not cfg.get("notify", True):
            return
        for probe in new:
            verdict = str(probe.get("verdict") or "").upper()
            good = verdict in ("MATCH", "UPGRADED") or probe.get("is_upgrade") is True
            if good and not cfg.get("notify_on_ok", False):
                continue
            if not good and verdict not in ("MISMATCH", "DOWNGRADED!", "SUSPICIOUS", "UNLISTED") and not probe.get("is_downgrade") and not probe.get("is_suspicious"):
                continue
            message = self._probe_line(probe)
            if self.tray:
                self.tray.showMessage(tr("Probe result", "探测结果"), message[:800], QSystemTrayIcon.MessageIcon.Information, 10000)
            if cfg.get("sound", True):
                QApplication.beep()
        for message in new_evidence:
            if self.tray:
                self.tray.showMessage(tr("Passive downgrade evidence", "被动降级证据"), message[:800],
                                      QSystemTrayIcon.MessageIcon.Warning, 10000)
            if cfg.get("sound", True):
                QApplication.beep()

    def _scheduler_tick(self) -> None:
        snap = self.snapshot_data or {}
        threads = snap.get("threads") or []
        if self.demo:
            return
        if any(t.get("due") and t.get("active") and not t.get("probe_running") and not t.get("halted")
               and t.get("id") not in self.pending_probes for t in threads):
            self.backend.run(["tick"], key="tick", timeout_ms=30000)
        import time
        now = time.time()
        if (snap.get("fresh_due") and not snap.get("global_running") and "fresh" not in self.backend.busy
                and not self.pending_fresh_at and now - self.last_fresh_heartbeat > 300):
            self.last_fresh_heartbeat = now
            if self.backend.run(["worker", "--fresh", "--detach"], key="fresh", timeout_ms=30000):
                self.pending_fresh_at = now
                self.fresh_button.setEnabled(False)

    def probe_selected(self) -> None:
        thread = self._selected_thread()
        if thread:
            tid = thread["id"]
            if self.backend.run(["worker", "--thread", tid, "--detach"], key="probe:" + tid, timeout_ms=30000):
                import time
                self.pending_probes[tid] = time.time()
                self._selection_changed()

    def retry_selected(self) -> None:
        self.probe_selected()

    def resume_selected(self) -> None:
        thread = self._selected_thread()
        if thread and not self.demo:
            self.backend.run(["resume", "--thread", thread["id"]], key="resume:" + thread["id"], timeout_ms=30000)

    def probe_fresh(self) -> None:
        if self.pending_fresh_at or "fresh" in self.backend.busy:
            return
        args = ["worker", "--fresh", "--detach"]
        if self.model_input.text().strip():
            args += ["--model", self.model_input.text().strip()]
        if self.effort_input.currentText().strip():
            args += ["--effort", self.effort_input.currentText().strip()]
        if self.backend.run(args, key="fresh", timeout_ms=30000):
            import time
            self.pending_fresh_at = time.time()
            self.fresh_button.setEnabled(False)

    def copy_report(self) -> None:
        QApplication.clipboard().setText(self.report.toPlainText())
        self.substatus.setText(tr("Report copied.", "报告已复制。"))

    def install_plugin(self) -> None:
        if self.demo:
            return
        self.backend.run(["setup", "--trust-hooks"], key="setup", timeout_ms=240000)

    def trust_hooks(self) -> None:
        if not self.demo:
            self.backend.run(["hooks", "trust"], key="trust", timeout_ms=90000)

    def settings(self) -> None:
        busy = self.backend.busy - {"snapshot"}
        live = self.snapshot_data or {}
        if busy or self.pending_probes or self.pending_fresh_at or live.get("global_running") or any(t.get("probe_running") for t in live.get("threads", [])):
            QMessageBox.information(self, tr("Backend is busy", "核心仍在运行"),
                                    tr("Wait for the active probe/setup operation to finish before changing profiles.",
                                       "请等当前探测或安装操作完成后再切换后端。"))
            return
        if self.demo:
            return
        dialog = SettingsDialog(self.backend, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            old_profile = dict(self.backend.profile)
            if not self.backend.save_profile(dialog.profile()):
                return
            if dialog.autostart_changed():
                try:
                    _set_autostart(dialog.autostart_enabled())
                except Exception as exc:
                    self._show_error(tr("Could not update user startup setting: ", "无法更新用户级自启动：") + str(exc))
            profile_changed = self.backend.profile != old_profile
            if profile_changed:
                self.pending_probes.clear()
                self.pending_fresh_at = None
                self.seen_probe_ids = None
                self.seen_evidence_ids = None
                # The dialog was populated from the old backend's snapshot. Never
                # apply its config controls to the newly selected home.
                self._config_queue.clear()
                self.refresh()
                return
            self._config_queue = dialog.config_updates()
            self._start_next_config()

    def _start_next_config(self) -> None:
        if not self._config_queue:
            self.refresh()
            return
        key, value = self._config_queue.pop(0)
        if not self.backend.run(["config", "set", key, value], key="config:" + key, timeout_ms=30000):
            self._config_queue.clear()

    def _show_plugin_status(self, snap: dict) -> None:
        hooks = snap.get("hooks") or {}
        install = snap.get("install") or {}
        self.setup_status.setPlainText(
            f"{tr('Plugin enabled', '插件已启用')}: {install.get('plugin_enabled', '?')}\n"
            f"{tr('Codex found', '找到 Codex')}: {install.get('codex_found', '?')}\n"
            f"{tr('Hooks', 'Hooks')}: {hooks.get('state', '?')} ({hooks.get('trusted', '?')}/{hooks.get('total', '?')} {tr('trusted', '已信任')})\n"
            f"{tr('Last hook event', '最近 hook 事件')}: {snap.get('hooks_last_event_ago') or '—'}")

    def settings_target(self) -> None:
        self.settings()

    def _target_text(self) -> str:
        if self.backend.profile.get("kind") == "wsl":
            return "WSL · " + (self.backend.profile.get("distro") or "?")
        return tr("Native", "本机")

    @staticmethod
    def _status_word(status: str) -> str:
        return {"ok": tr("OK", "正常"), "alert": tr("Alert", "警告"), "warn": tr("Suspicious", "可疑"),
                "upgraded": tr("Upgraded", "已升级"), "unverified": tr("Unverified", "未验证")}.get(status, status)

    @staticmethod
    def _thread_state(thread: dict) -> str:
        if thread.get("probe_running"):
            return tr("Probing…", "探测中…")
        if thread.get("halted"):
            return tr("Halted", "已暂停")
        if thread.get("alert"):
            return tr("Downgrade", "降级")
        if thread.get("suspicious"):
            return tr("Suspicious", "可疑")
        if thread.get("upgraded"):
            return tr("Upgrade", "升级")
        return tr("Due" if thread.get("due") else "OK", "待探测" if thread.get("due") else "正常")

    @staticmethod
    def _probe_line(probe: dict) -> str:
        when = probe.get("finished_ago") or probe.get("finished") or ""
        verdict = probe.get("verdict") or probe.get("status") or "?"
        direction = probe.get("direction") or ""
        expected = probe.get("expected") or "?"
        prediction = probe.get("prediction") or "?"
        probability = probe.get("probability")
        pct = f"{round(probability * 100)}%" if isinstance(probability, (int, float)) else ""
        return f"{when} · {verdict} {direction} · {expected} → {prediction} {pct}".strip()

    @staticmethod
    def _iso_time(value: str) -> float:
        from datetime import datetime
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError):
            return 0.0

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.tray and not self._closing:
            event.ignore()
            self.hide()
            if self.tray:
                self.tray.showMessage("is-gpt-nerfed", tr("Panel hidden in the system tray.", "面板已隐藏到系统托盘。"),
                                      QSystemTrayIcon.MessageIcon.Information, 2500)
        elif not self._closing:
            event.ignore()
            self.showNormal()
            self.substatus.setText(tr("No system tray is available. Use Exit to quit the app.",
                                      "当前没有系统托盘。请使用“退出”按钮关闭应用。"))
        else:
            event.accept()

    def explicit_exit(self) -> None:
        self._closing = True
        if self.tray:
            self.tray.hide()
        self.app.quit()


def run(demo: bool = False, screenshot: str | None = None) -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName("is-gpt-nerfed")
    app.setOrganizationName("is-gpt-nerfed")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    backend = Backend(demo=demo)
    win = MainWindow(backend, app)
    if screenshot:
        captured = False
        def save_demo_shot(_snap: dict) -> None:
            nonlocal captured
            if captured:
                return
            captured = True
            def capture_and_exit() -> None:
                win.grab().save(screenshot)
                app.exit(0)
            QTimer.singleShot(250, capture_and_exit)
        backend.snapshotReady.connect(save_demo_shot)
        QTimer.singleShot(30000, lambda: app.exit(0))
    win.show()
    return app.exec()
