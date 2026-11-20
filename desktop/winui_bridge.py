"""Windows-only: drives the WinUI 3 inspector (windows-ui/Inspector) in place of the Qt table window.

The WinUI process is a pure view. Every decision stays in MainWindow: this module turns its state into a
ready-to-render view model (texts already localized, buttons already enabled/disabled) and sends it as JSON
lines on the child's stdin; the child answers with JSON action lines on stdout. Closing the inspector window
just hides it; when the tray app quits, stdin closes and the child exits on its own.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, QProcess

if TYPE_CHECKING:  # pragma: no cover
    from .main import MainWindow

EXE_NAME = "IsGPTNerfed.Inspector.exe"


def inspector_path() -> Path | None:
    """返回打包附带或本地开发构建的 WinUI 3 检查器可执行文件路径。"""
    if sys.platform != "win32" or os.environ.get("NERFED_QT_INSPECTOR"):
        return None
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent / "inspector" / EXE_NAME
        return exe if exe.is_file() else None
    repo = Path(__file__).resolve().parents[1]
    raw = [
        repo / "dist" / "windows" / "inspector" / EXE_NAME,
        *(repo / "windows-ui" / "Inspector" / "bin").glob(f"**/win-x64/{EXE_NAME}"),
    ]
    candidates = [p for p in raw if p.is_file()]
    if not candidates:
        return None
    # 优先选择同目录存在 PRI 索引且构建时间最新的产物，避免非打包 WinUI 启动失败。
    with_pri = [p for p in candidates if p.with_suffix(".pri").is_file()]
    if with_pri:
        return max(with_pri, key=lambda p: p.stat().st_mtime)
    return candidates[0]


class WinUIInspector(QObject):
    def __init__(self, win: "MainWindow", exe: Path, tr: Callable[[str, str], str], icon: Path,
                 fallback: Callable[[str | None], None] | None = None) -> None:
        super().__init__(win)
        self.win = win
        self.icon = icon
        self.exe = exe
        self._tr = tr
        self._fallback = fallback
        self.proc: QProcess | None = None
        self._buffer = b""
        self._stderr = b""
        self._pending_show: list[str | None] = []
        self._pending_logs: list[str] = []
        self._ready = False
        self._closing = False
        self._starting = False

    # ---- process lifecycle

    def _ensure(self) -> bool:
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            return True
        self._closing = False
        self._ready = False
        self._buffer = b""
        proc = QProcess(self)
        proc.setProgram(str(self.exe))
        proc.setWorkingDirectory(str(self.exe.parent))
        proc.readyReadStandardOutput.connect(self._read)
        proc.readyReadStandardError.connect(self._read_stderr)
        proc.finished.connect(lambda *_: self._exited())
        proc.errorOccurred.connect(self._start_failed)
        self.proc = proc
        self._stderr = b""
        self._starting = True
        try:
            proc.start()
            return proc.waitForStarted(5000)
        finally:
            self._starting = False

    def _stderr_summary(self) -> str:
        """One readable line from a .NET crash: the exception's message, not the bottom of its stack trace."""
        text = self._stderr.decode("utf-8", "replace")
        if "\ufffd" in text:  # .NET writes stderr in the console's ANSI codepage, not UTF-8
            try:
                text = self._stderr.decode("mbcs")
            except (LookupError, UnicodeDecodeError):
                pass
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for i, line in enumerate(lines):
            if "Exception" in line:
                detail = next((l for l in lines[i + 1:] if not l.startswith("at ")), "")
                return " ".join(x for x in (line.split(": ", 1)[-1], detail) if x)[:300]
        return lines[-1][:300] if lines else ""

    def _trigger_fallback(self) -> None:
        last_tid = self._pending_show[-1] if self._pending_show else None
        self._pending_show.clear()
        cb = self._fallback or getattr(self.win, "_open_qt_inspector", None)
        if callable(cb):
            cb(last_tid)

    @staticmethod
    def _allow_foreground(proc: QProcess | None) -> None:
        if sys.platform != "win32" or proc is None:
            return
        pid = int(proc.processId())
        if pid > 0:
            try:
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(pid)
            except Exception:
                pass

    def _start_failed(self, err: QProcess.ProcessError) -> None:
        if self._closing or self.proc is None:
            return
        self._read_stderr()
        if err not in (QProcess.ProcessError.FailedToStart, QProcess.ProcessError.Crashed):
            return
        self.proc = None
        was_ready, self._ready = self._ready, False
        summary = self._stderr_summary()
        self.win._show_error(f"WinUI inspector: {err.name}" + (f" — {summary}" if summary else ""))
        if not was_ready and not self._starting:
            self._trigger_fallback()

    def _read_stderr(self) -> None:
        if self.proc is not None:
            self._stderr = (self._stderr + bytes(self.proc.readAllStandardError().data()))[-4000:]

    def _exited(self) -> None:
        proc, self.proc = self.proc, None
        was_ready, self._ready = self._ready, False
        if proc is None or self._closing:
            return
        self._stderr = (self._stderr + bytes(proc.readAllStandardError().data()))[-4000:]
        summary = self._stderr_summary()
        if was_ready:
            # ready 之后异常退出也需要告知用户，不再静默吞掉。
            self.win._show_error(f"WinUI inspector exited unexpectedly ({proc.exitCode()}): {summary or 'no output'}")
            return
        self.win._show_error(f"WinUI inspector exited before it was ready ({proc.exitCode()}): {summary or 'no output'}")
        if not self._starting:
            self._trigger_fallback()

    def show(self, thread_id: str | None = None) -> bool:
        if not self._ensure():
            return False
        if self._ready:
            self._allow_foreground(self.proc)
            self._send({"type": "show", "thread": thread_id})
        else:
            self._pending_show.append(thread_id)
        return True

    def close(self) -> None:
        self._closing = True
        if self.proc is not None:
            self.proc.closeWriteChannel()
            if not self.proc.waitForFinished(1500):
                self.proc.kill()

    # ---- Qt → WinUI

    def _send(self, message: dict) -> None:
        if self.proc is None or self.proc.state() != QProcess.ProcessState.Running:
            return
        self.proc.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))

    def push_state(self) -> None:
        if self._ready:
            self._send({"type": "state", **self.view_model()})

    def log(self, text: str) -> None:
        if self._ready:
            self._send({"type": "log", "text": text})
        else:
            self._pending_logs.append(text)
            if len(self._pending_logs) > 100:
                self._pending_logs = self._pending_logs[-100:]

    def error(self, text: str) -> None:
        if self._ready:
            self._send({"type": "error", "text": text})

    def strings(self) -> dict:
        tr = self._tr
        return {
            "title": "is-gpt-nerfed",
            "refresh": tr("Refresh", "刷新"), "settings": tr("Settings", "设置"), "exit": tr("Exit", "退出"),
            "sessions": tr("Sessions", "会话"), "fresh_tab": tr("Fresh probe", "全新探测"), "plugin": tr("Plugin", "插件"),
            "col_session": tr("Session", "会话"), "col_model": tr("Model", "模型"), "col_effort": tr("Effort", "推理强度"),
            "col_state": tr("State", "状态"), "col_evidence": tr("Evidence", "证据"),
            "report_placeholder": tr("Select a session to inspect its report and evidence history.",
                                     "选择会话以查看报告和证据历史。"),
            "history_placeholder": tr("Probe history", "探测历史"),
            "report": tr("Report", "报告"), "history": tr("History", "探测历史"),
            "probe": tr("Probe selected session", "探测所选会话"), "retry": tr("Retry failed probe", "重试失败探测"),
            "resume": tr("Resume halted session", "恢复已暂停会话"), "copy": tr("Copy report", "复制报告"),
            "copied": tr("Report copied.", "报告已复制。"),
            "fresh_hint": tr("Fresh session probe uses the configured default model and effort.",
                             "全新会话探测使用配置的默认模型与推理强度。"),
            "model_placeholder": tr("Default model (optional)", "默认模型（可选）"),
            "effort_placeholder": tr("Effort (optional)", "推理强度（可选）"),
            "fresh": tr("Probe fresh session", "探测全新会话"),
            "plugin_hint": tr("Plugin installation and hook trust only run after you press a button.",
                              "只有点击按钮后才会安装插件或信任 hooks。"),
            "install": tr("Install plugin", "安装插件"), "trust": tr("Trust hooks", "信任 hooks"),
            "status": tr("Status", "状态"), "activity": tr("Activity", "操作记录"),
            "error_title": tr("Operation error", "操作错误"),
            "demo": tr("DEMO MODE · offline sample data · no Codex home or model calls",
                       "演示模式 · 离线样例 · 不读取 Codex home，也不会请求模型"),
            "empty": tr("No sessions yet.", "暂无会话。"),
        }

    def view_model(self) -> dict:
        w = self.win
        snap = w.snapshot_data or {}
        demo = w.demo
        busy = w.backend.busy
        overall = snap.get("overall") or {}
        state = str(overall.get("status", "unknown")) if snap else "unknown"
        message = str(overall.get("message", ""))
        threads = []
        for t in snap.get("threads") or []:
            tid = str(t.get("id") or "")
            failure = t.get("last_failure")
            probing = ("probe:" + tid) in busy or tid in w.pending_probes
            history = []
            for item in t.get("evidence") or []:
                active = "active" if item.get("active", True) else "reverted"
                history.append(f"[{item.get('severity') or 'evidence'} · {active} · {item.get('ago') or item.get('ts') or ''}] "
                               f"{item.get('text', '')}")
            if history:
                history.append("")
            history += [w._probe_line(p) for p in t.get("probes") or []]
            if failure:
                history.insert(0, self._tr("Latest failed attempt: ", "最近失败尝试：") + w._probe_line(failure))
            threads.append({
                "id": tid, "title": str(t.get("title") or tid), "model": str(t.get("model") or "—"),
                "effort": str(t.get("effort") or "—"), "state": w._thread_state(t),
                "evidence": str(t.get("last_evidence") or ""), "alert": bool(t.get("alert")),
                "suspicious": bool(t.get("suspicious")),
                "report": str(t.get("report_text") or ""), "history": "\n".join(history),
                "can_probe": not demo and not probing and not t.get("probe_running"),
                "can_retry": not demo and not probing and bool(failure and failure.get("retryable")),
                "can_resume": not demo and bool(t.get("halted")),
            })
        hooks = snap.get("hooks") or {}
        install = snap.get("install") or {}
        tr = self._tr
        plugin_status = (
            f"{tr('Plugin enabled', '插件已启用')}: {install.get('plugin_enabled', '?')}\n"
            f"{tr('Codex found', '找到 Codex')}: {install.get('codex_found', '?')}\n"
            f"Hooks: {hooks.get('state', '?')} ({hooks.get('trusted', '?')}/{hooks.get('total', '?')} {tr('trusted', '已信任')})\n"
            f"{tr('Last hook event', '最近 hook 事件')}: {snap.get('hooks_last_event_ago') or '—'}") if snap else ""
        if snap:
            headline = f"{w._status_word(state)} · {message}"
            sub = tr(f"Updated {snap.get('generated', '')} · {w._target_text()}",
                     f"更新于 {snap.get('generated', '')} · {w._target_text()}")
        else:
            headline = tr("Connecting…", "正在连接…")
            sub = tr("Waiting for local snapshot…", "等待本地状态…")
        return {
            "status": state, "headline": headline, "substatus": sub, "demo": demo,
            "threads": threads,
            "fresh_enabled": (not demo and bool(snap) and not snap.get("global_running")
                              and not w.pending_fresh_at and "fresh" not in busy),
            "global_report": str(snap.get("global_report_text") or ""),
            "plugin_status": plugin_status,
            "setup_enabled": not demo and "setup" not in busy,
            "trust_enabled": not demo and "trust" not in busy,
            "settings_enabled": not demo,
        }

    # ---- WinUI → Qt

    def _read(self) -> None:
        if self.proc is None:
            return
        self._buffer += bytes(self.proc.readAllStandardOutput())
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            try:
                message = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(message, dict):
                self._handle(message)

    def _handle(self, m: dict) -> None:
        w = self.win
        action = m.get("action")
        tid = str(m.get("thread") or "")
        if action == "ready":
            self._ready = True
            self._send({"type": "init", "strings": self.strings(),
                        "icon": str(self.icon)})
            self.push_state()
            for entry in self._pending_logs:
                self._send({"type": "log", "text": entry})
            self._pending_logs.clear()
            self._allow_foreground(self.proc)
            for thread in self._pending_show or [None]:
                self._send({"type": "show", "thread": thread})
            self._pending_show.clear()
        elif action == "refresh":
            w.refresh()
        elif action == "settings":
            w.settings()
        elif action == "exit":
            w.explicit_exit()
        elif action in ("probe", "retry") and tid:
            w.probe_thread(tid)
        elif action == "resume" and tid and not w.demo:
            w.resume_thread(tid)
        elif action == "fresh":
            w.probe_fresh_with(str(m.get("model") or ""), str(m.get("effort") or ""))
        elif action == "install":
            w.install_plugin()
        elif action == "trust":
            w.trust_hooks()
        self.push_state()
