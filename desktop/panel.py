"""Tray panel that mirrors the upstream macOS menu-bar popover (PanelView.swift).

Layout, copy and colours follow the SwiftUI panel: a centred face and headline,
"Active sessions" and "Fresh session" groups with rows that open in place, and a
quiet footer. Settings replace the lists on the same page, as on macOS. Actions
are delegated to the MainWindow controller, which owns probe/notify state.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QCursor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QPainter,
                           QPainterPath, QPalette, QPixmap)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

try:
    from .backend_l10n import BackendL10n
except ImportError:
    from backend_l10n import BackendL10n

ASSETS = Path(__file__).resolve().parent / "assets"
WIDTH = 420


# --------------------------------------------------------------------------- localisation

def _load_strings(path: Path) -> dict[str, str]:
    table: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return table
    for key, value in re.findall(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)";', text, re.MULTILINE):
        unescape = lambda s: s.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        table[unescape(key)] = unescape(value)
    return table


def _zh() -> bool:
    from PySide6.QtCore import QLocale
    return QLocale.system().name().lower().startswith("zh")


_TABLE = _load_strings(ASSETS / "zh-Hans.strings") if _zh() else {}
B = BackendL10n(_load_strings(ASSETS / "zh-Hans.backend.strings") if _zh() else {})


def L(key: str, *args: object) -> str:
    """L10n.tr: Localizable.strings lookup with `%@` arguments, English key as fallback."""
    out = _TABLE.get(key, key)
    for a in args:
        out = out.replace("%@", str(a), 1)
    return out


def ago(value: str | None) -> str:
    if not value:
        return ""
    m = re.match(r"^(\d+)([smhd]) ago$", value)
    return L(f"%@{m.group(2)} ago", m.group(1)) if m else value


def status_message(message: str) -> str:
    out = []
    for part in message.split(" · "):
        if part in ("fresh session downgraded", "all clear", "no active threads"):
            out.append(L(part))
            continue
        n, _, rest = part.partition(" ")
        if not n.isdigit() or rest not in ("downgraded", "suspicious", "upgraded", "unverified",
                                           "probe running", "probes running"):
            return message
        out.append(L("%@ " + rest, n))
    return " · ".join(out)


def report_copy(text: str, title: str, display: str) -> str:
    """L10n.report: swap the header's title for the displayed one, translate the generated lines."""
    lines = text.split("\n")
    prefix = f"is-gpt-nerfed · {title} · "
    if not lines or not lines[0].startswith(prefix):
        return text
    header = f"is-gpt-nerfed · {display} · " + lines[0][len(prefix):]
    return header if len(lines) == 1 else header + "\n" + B("\n".join(lines[1:]))


def pct(p: object) -> str:
    return f"{round(float(p) * 100)}%" if isinstance(p, (int, float)) else ""


# --------------------------------------------------------------------------- theme

class Theme:
    def __init__(self) -> None:
        dark = False
        try:
            dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except AttributeError:
            dark = QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128
        self.dark = dark
        base = QColor(255, 255, 255) if dark else QColor(0, 0, 0)
        self.bg = QColor(30, 30, 32, 246) if dark else QColor(246, 246, 248, 248)
        self.border = QColor(255, 255, 255, 30) if dark else QColor(0, 0, 0, 28)
        self.primary = QColor(base.red(), base.green(), base.blue(), 235 if dark else 225)
        self.secondary = QColor(base.red(), base.green(), base.blue(), 150 if dark else 140)
        self.tertiary = QColor(base.red(), base.green(), base.blue(), 95 if dark else 80)
        self.group = QColor(base.red(), base.green(), base.blue(), 16 if dark else 12)
        self.hover = QColor(base.red(), base.green(), base.blue(), 10)
        self.sep = QColor(base.red(), base.green(), base.blue(), 26 if dark else 22)
        self.button = QColor(base.red(), base.green(), base.blue(), 26 if dark else 20)
        self.red = QColor("#ff453a" if dark else "#ff3b30")
        self.orange = QColor("#ff9f0a" if dark else "#ff9500")
        self.green = QColor("#30d158" if dark else "#28cd41")

    @staticmethod
    def css(c: QColor) -> str:
        return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


def font(size: int, bold: bool = False) -> QFont:
    f = QFont(QApplication.font())
    if sys.platform == "win32":
        f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI"])
    f.setPixelSize(size)
    f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return f


# Type scale from Glass.swift (pt on macOS ~ px here; text bumped one step for Windows legibility).
HEADLINE, TITLE, TEXT = 17, 13, 12


def _windows_acrylic(hwnd: int, theme: "Theme") -> bool:
    """Blur-behind for the frameless panel (Windows 10 1803+/11), rounded by DWM on Windows 11.

    Uses SetWindowCompositionAttribute(ACCENT_ENABLE_ACRYLICBLURBEHIND); DWM system backdrops (Mica)
    do not render behind the layered windows Qt creates for translucent widgets. Any failure keeps
    the opaque painted background, so this is purely cosmetic.
    """
    if sys.platform != "win32" or os.environ.get("NERFED_NO_ACRYLIC"):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class AccentPolicy(ctypes.Structure):
            _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                        ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

        class CompositionData(ctypes.Structure):
            _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]

        if sys.getwindowsversion().build < 22000:  # Win10 acrylic lags while dragging and has square corners
            return False
        tint = theme.bg
        abgr = (0x01 << 24) | (tint.blue() << 16) | (tint.green() << 8) | tint.red()
        accent = AccentPolicy(4, 0, abgr, 0)  # ACCENT_ENABLE_ACRYLICBLURBEHIND
        data = CompositionData(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))
        user32 = ctypes.windll.user32
        user32.SetWindowCompositionAttribute.argtypes = [wintypes.HWND, ctypes.c_void_p]
        if not user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(data)):
            return False
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- primitives

class Text(QLabel):
    """Single-line label that elides instead of widening the panel."""

    def __init__(self, text: str = "", color: QColor | None = None, size: int = TEXT, bold: bool = False,
                 elide: bool = True, wrap: bool = False, center: bool = False) -> None:
        super().__init__()
        self._full = text
        self._elide = elide and not wrap
        self.setFont(font(size, bold))
        if color is not None:
            self.setStyleSheet(f"color: {Theme.css(color)}; background: transparent")
        self.setWordWrap(wrap)
        if center:
            self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        if self._elide:
            self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.setMinimumWidth(0)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        self._full = text
        self._apply()

    def sizeHint(self) -> QSize:  # noqa: N802
        if not self._elide:
            return super().sizeHint()
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self._full) + 2, fm.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        if self._elide and self.width() > 0:
            shown = QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        else:
            shown = self._full
        QLabel.setText(self, shown)
        if shown != self._full:
            self.setToolTip(self._full)


class Dot(QWidget):
    def __init__(self, color: QColor) -> None:
        super().__init__()
        self.color = color
        self.setFixedSize(7, 7)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(0, self.height() - 7, 7, 7)


class RowButton(QPushButton):
    """Small text capsule (Probe / Retry / Resume)."""

    def __init__(self, title: str, theme: Theme, action: Callable[[], None], destructive: bool = False) -> None:
        super().__init__(title)
        self.setFont(font(TEXT, True))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        fg = theme.red if destructive else theme.primary
        hover = QColor(theme.button)
        hover.setAlpha(min(255, hover.alpha() * 2))
        self.setStyleSheet(
            f"QPushButton {{ color: {Theme.css(fg)}; background: {Theme.css(theme.button)}; border: none;"
            f" border-radius: 11px; padding: 3px 12px; min-height: 16px }}"
            f" QPushButton:hover {{ background: {Theme.css(hover)} }}"
            f" QPushButton:disabled {{ color: {Theme.css(theme.tertiary)} }}")
        self.clicked.connect(lambda: action())


class TextButton(QPushButton):
    def __init__(self, title: str, color: QColor, action: Callable[[], None]) -> None:
        super().__init__(title)
        self.setFont(font(TEXT, True))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet(f"QPushButton {{ color: {Theme.css(color)}; background: transparent; border: none; padding: 0 }}"
                           f" QPushButton:hover {{ text-decoration: underline }}")
        self.clicked.connect(lambda: action())


class Switch(QAbstractButton):
    def __init__(self, on: bool, theme: Theme) -> None:
        super().__init__()
        self.theme = theme
        self.setCheckable(True)
        self.setChecked(on)
        self.setFixedSize(30, 17)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        p.setPen(Qt.PenStyle.NoPen)
        track = self.theme.green if on else QColor(self.theme.secondary.red(), self.theme.secondary.green(),
                                                    self.theme.secondary.blue(), 70)
        if not self.isEnabled():
            track.setAlpha(track.alpha() // 2)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 30, 17), 8.5, 8.5)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(14.5 if on else 1.5, 1.5, 14, 14))


class Segments(QWidget):
    changed = Signal(str)

    def __init__(self, options: list[str], selected: str, theme: Theme) -> None:
        super().__init__()
        self.setObjectName("seg")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.setStyleSheet(f"#seg {{ background: {Theme.css(theme.button)}; border-radius: 7px }}")
        sel_bg = QColor(70, 70, 74) if theme.dark else QColor(255, 255, 255)
        for o in options:
            b = QPushButton(o)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(font(TEXT, o == selected))
            bg = Theme.css(sel_bg) if o == selected else "transparent"
            b.setStyleSheet(f"QPushButton {{ color: {Theme.css(theme.primary)}; background: {bg}; border: none;"
                            f" border-radius: 5px; padding: 2px 8px }}")
            b.clicked.connect(lambda _=False, v=o: self.changed.emit(v))
            lay.addWidget(b)


class Group(QWidget):
    """Title (+ trailing) over one rounded container; rows separated by hairlines."""

    def __init__(self, title: str, theme: Theme, trailing: str | None = None) -> None:
        super().__init__()
        self.theme = theme
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(5)
        head = QHBoxLayout()
        head.setContentsMargins(2, 0, 2, 0)
        head.addWidget(Text(title, theme.secondary, bold=True, elide=False))
        head.addStretch(1)
        if trailing:
            t = Text(trailing, theme.tertiary)
            t.setAlignment(Qt.AlignmentFlag.AlignRight)
            head.addWidget(t, 1)
        outer.addLayout(head)
        self.box = QFrame()
        self.box.setObjectName("groupbox")
        self.box.setStyleSheet(f"#groupbox {{ background: {Theme.css(theme.group)}; border-radius: 9px }}")
        self.rows = QVBoxLayout(self.box)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(0)
        outer.addWidget(self.box)
        self._count = 0

    def add(self, widget: QWidget) -> None:
        if self._count:
            sep = QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background: {Theme.css(self.theme.sep)}; margin-left: 10px")
            self.rows.addWidget(sep)
        self.rows.addWidget(widget)
        self._count += 1


def hline(*parts: QWidget, spacing: int = 4) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for i, part in enumerate(parts):
        lay.addWidget(part, 1 if isinstance(part, Text) and part._elide and i == len(parts) - 1 else 0)
    if not any(isinstance(p, Text) and p._elide for p in parts):
        lay.addStretch(1)
    return w


# --------------------------------------------------------------------------- verdict presentation

def tint(p: dict, t: Theme) -> QColor:
    if p.get("is_downgrade") is True:
        return t.red
    if p.get("is_upgrade") is True:
        return t.green
    v = p.get("verdict")
    if v == "MATCH":
        return t.green
    if v in ("MISMATCH", "SUSPICIOUS"):
        return t.orange
    return t.secondary


def word(p: dict) -> str:
    v, d = p.get("verdict"), p.get("direction")
    if not v:
        return L("Failed" if p.get("status") == "failed" else "…")
    if v == "DOWNGRADED!":
        return L("Downgraded")
    if v == "MISMATCH":
        return L({"downgrade": "Downgrade", "upgrade": "Upgrade"}.get(d or "", "Rerouted"))
    return L({"SUSPICIOUS": "Suspicious", "MATCH": "Match", "UNLISTED": "Unlisted", "INVALID": "Invalid"}.get(v, v.capitalize()))


def is_failure(p: dict) -> bool:
    return p.get("verdict") == "INVALID" or p.get("status") == "failed"


def detail(p: dict) -> str:
    parts: list[str] = []
    if is_failure(p):
        errs = p.get("errors") or []
        parts.append(B(errs[0]) if errs else L("no usable sample"))
    elif p.get("stale_account") is True:
        parts.append(p.get("prediction") or "?")
    else:
        s = p.get("prediction") or "?"
        if pct(p.get("probability")):
            s += " " + pct(p.get("probability"))
        e = p.get("expected")
        if e and e != p.get("prediction") and p.get("p_expected") is not None:
            s += ", " + L("declared %@", pct(p.get("p_expected")))
        parts.append(s)
        n, q = p.get("used_outputs"), p.get("queries")
        if isinstance(n, int) and isinstance(q, int) and n < q:
            parts.append(L("%@ of %@ answers", n, q))
        if (p.get("rounds") or 0) > 1:
            parts.append(L("%@ rounds", p["rounds"]))
    r = p.get("retries") or 0
    if r > 0:
        parts.append(L("retried once") if r == 1 else L("retried %@×", r))
    return " · ".join(parts)


def verdict_line(p: dict, t: Theme) -> QWidget:
    stale = p.get("stale_account") is True
    dot = lambda: Text("·", t.tertiary, elide=False)
    parts: list[QWidget]
    if stale:
        tail = L("%@, account unknown", word(p)) if p.get("account_state") == "unknown" else L("%@, another account", word(p))
        parts = [Text(L("Unverified"), t.secondary, bold=True, elide=False), dot(), Text(tail, t.tertiary)]
    else:
        parts = [Text(word(p), tint(p, t), bold=True, elide=False), dot(), Text(detail(p), t.secondary)]
    a = ago(p.get("finished_ago"))
    if a:
        parts += [dot(), Text(a, t.tertiary, elide=False)]
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    for part in parts:
        lay.addWidget(part, 0)
    # the detail elides; the age stays whole and directly after it (as SwiftUI's lineLimit(1) does)
    parts[2].setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
    lay.addStretch(1)
    errs = p.get("errors") or []
    w.setToolTip("\n".join(B(e) for e in errs) if errs else B(p.get("quote") or ""))
    return w


def evidence_text(text: str, a: str | None, active: bool) -> str:
    out = B(text)
    if ago(a):
        out += " · " + ago(a)
    if not active:
        out += " · " + L("reverted")
    return out


def report_lines(probes: list[dict], evidence: list[dict], failure: dict | None, t: Theme) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)

    def fact(label: str, value: str, color: QColor | None = None) -> None:
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        lab = Text(label, t.tertiary, elide=False)
        lab.setFixedWidth(70)
        lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        val = Text(value, color or t.secondary, wrap=True)
        rl.addWidget(lab, 0, Qt.AlignmentFlag.AlignTop)
        rl.addWidget(val, 1)
        lay.addWidget(row)

    if probes:
        p = probes[0]
        lay.addWidget(verdict_line(p, t))
        res = p.get("results") or []
        if res and not is_failure(p) and p.get("stale_account") is not True:
            fact(L("Fingerprint"), " · ".join(f"{r.get('model') or '?'} {pct(r.get('probability'))}" for r in res))
        for e in p.get("errors") or []:
            fact(L("Problem"), B(e), t.orange)
        if p.get("stale_account") is True:
            fact(L("Account"), L("recorded before accounts were tracked; it cannot vouch for the signed-in account")
                 if p.get("account_state") == "unknown" else L("probed under another Codex account; it does not vouch for this one"))
    else:
        lay.addWidget(Text(L("No probe yet"), t.tertiary))
    if failure:
        attempt = L("failed") + (" " + ago(failure.get("finished_ago")) if ago(failure.get("finished_ago")) else "")
        errs = failure.get("errors") or []
        bits = [attempt, B(errs[0]) if errs else L("no usable answer")]
        r = failure.get("retries") or 0
        if r:
            bits.append(L("retried once") if r == 1 else L("retried %@×", r))
        fact(L("Attempt"), " · ".join(bits))
    for p in probes[1:5]:
        lay.addWidget(hline(Text(L("Earlier"), t.tertiary, elide=False), Text("·", t.tertiary, elide=False), verdict_line(p, t)))
    for e in evidence:
        on = e.get("active", True)
        sev = e.get("severity")
        color = (t.red if sev == "hard" else t.orange if sev == "soft" else t.green) if on else t.secondary
        lay.addWidget(Text(evidence_text(e.get("text", ""), e.get("ago"), on), color, wrap=True))
    return w


# --------------------------------------------------------------------------- rows

class ExpandableRow(QFrame):
    def __init__(self, can_open: bool, toggle: Callable[[], None], theme: Theme) -> None:
        super().__init__()
        self.can_open, self.toggle, self.theme = can_open, toggle, theme
        self.setObjectName("row")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if can_open:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_builder: Callable[[QMenu], None] | None = None

    def event(self, e) -> bool:
        if e.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave) and self.can_open:
            bg = Theme.css(self.theme.hover) if e.type() == QEvent.Type.HoverEnter else "transparent"
            self.setStyleSheet(f"#row {{ background: {bg}; border-radius: 9px }}")
        return super().event(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.can_open and self.rect().contains(e.position().toPoint()):
            self.toggle()
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        if not self.menu_builder:
            return
        menu = QMenu(self)
        self.menu_builder(menu)
        if menu.actions():
            panel = self.window()
            if isinstance(panel, Panel):
                panel.hold = True
            menu.exec(e.globalPos())
            if isinstance(panel, Panel):
                panel.hold = False


# --------------------------------------------------------------------------- panel

class Panel(QWidget):
    """The popover. `ctl` is the MainWindow controller (actions, pending state, backend)."""

    def __init__(self, ctl, floating: bool = True) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        flags |= Qt.WindowType.Tool if floating else Qt.WindowType.Window
        super().__init__(None, flags)
        self.ctl = ctl
        self.floating = floating
        self.hold = False
        self.open: str | None = None
        self.show_settings = False
        self.theme = Theme()
        self.setWindowTitle("is-gpt-nerfed")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(WIDTH)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(12, 12, 12, 10)
        self.root.setSpacing(14)
        self._scroll_value = 0
        self._drag: QPoint | None = None
        self.acrylic = False
        self._backdrop_tried = False
        backend = ctl.backend
        backend.snapshotReady.connect(lambda _s: self.rebuild())
        backend.processStarted.connect(lambda k: k != "snapshot" and self.rebuild())
        backend.processFinished.connect(lambda k, *_: k != "snapshot" and self.rebuild())
        backend.error.connect(lambda _m: self.rebuild())
        self.rebuild()

    # ---- window behaviour

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if not self._backdrop_tried:
            self._backdrop_tried = True
            self.acrylic = _windows_acrylic(int(self.winId()), self.theme)
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.acrylic:
            # DWM blurs what is behind and rounds the corners; paint a tint over it like NSVisualEffectView.
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            tint = QColor(self.theme.bg)
            tint.setAlpha(150 if self.theme.dark else 165)
            p.fillRect(self.rect(), tint)
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.fillPath(path, self.theme.bg)
        p.setPen(self.theme.border)
        p.drawPath(path)

    def changeEvent(self, e) -> None:  # noqa: N802
        if (e.type() == QEvent.Type.ActivationChange and self.floating and not self.isActiveWindow()
                and not self.hold and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None):
            QTimer.singleShot(0, lambda: (not self.isActiveWindow() and not self.hold) and self.hide())
        super().changeEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape and self.floating:
            self.hide()
        super().keyPressEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if not self.floating and e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        self._drag = None

    def toggle_at(self, anchor: QRect | None) -> None:
        if self.isVisible():
            self.hide()
            return
        self.popup(anchor)

    def popup(self, anchor: QRect | None = None) -> None:
        self.rebuild()
        self.adjustSize()
        point = anchor.center() if anchor and anchor.isValid() else QCursor.pos()
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        size = self.sizeHint()
        h = min(size.height(), area.height() - 16)
        self.resize(WIDTH, h)
        x = min(max(point.x() - WIDTH // 2, area.left() + 8), area.right() - WIDTH - 8)
        # open away from the taskbar: above it when the tray is in the lower half, below it otherwise
        y = area.bottom() - h - 8 if point.y() > area.center().y() else area.top() + 8
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.ctl.refresh()

    # ---- building

    def _clear(self) -> None:
        if hasattr(self, "_list") and self._list is not None:
            self._scroll_value = self._list.verticalScrollBar().value()
        self._list = None
        while self.root.count():
            item = self.root.takeAt(0)
            old = item.widget() if item else None
            if old is not None:
                old.hide()
                old.setParent(None)
                old.deleteLater()

    def rebuild(self) -> None:
        self._clear()
        self.root.addWidget(self._header())
        if self.show_settings:
            self.root.addWidget(self._settings())
        else:
            setup = self._setup()
            if setup:
                self.root.addWidget(setup)
            self.root.addWidget(self._threads())
            self.root.addWidget(self._fresh())
        self.root.addWidget(self._footer())
        if self.isVisible():
            QTimer.singleShot(0, self._fit)

    def _fit(self) -> None:
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        bottom = self.geometry().bottom()
        anchored_low = bottom > area.center().y()
        h = min(self.sizeHint().height(), area.height() - 16)
        if h == self.height():
            return
        y = bottom - h + 1 if anchored_low and self.floating else self.y()
        self.setGeometry(self.x(), max(area.top() + 8, y), WIDTH, h)

    # ---- state helpers

    @property
    def snap(self) -> dict | None:
        return self.ctl.snapshot_data

    @property
    def error(self) -> str:
        return self.ctl.last_snapshot_error if not self.snap else ""

    def _counts(self) -> tuple[bool, bool, bool, bool]:
        o = (self.snap or {}).get("overall") or {}
        alert = (o.get("downgraded") or 0) > 0
        warn = not alert and (o.get("suspicious") or 0) > 0
        up = not alert and not warn and (o.get("upgraded") or 0) > 0
        return alert, warn, up, (o.get("running") or 0) > 0

    def _toggle(self, key: str) -> None:
        self.open = None if self.open == key else key
        self.rebuild()

    # ---- header

    def _header(self) -> QWidget:
        t = self.theme
        alert, warn, up, running = self._counts()
        if self.error:
            status = L("nerfed error: %@", B(self.error.splitlines()[0][:160]))
        elif not self.snap:
            status = L("Loading…")
        else:
            status = status_message(str((self.snap.get("overall") or {}).get("message", "")))
        parts = status.split(" · ")
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(3)
        face = QLabel()
        name = "face-alert" if alert else "face-warn" if warn else "face-ok"
        pix = QPixmap(str(ASSETS / f"{name}.png"))
        if not pix.isNull():
            dpr = self.devicePixelRatioF() or 1.0
            pix = pix.scaled(int(72 * dpr), int(72 * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            pix.setDevicePixelRatio(dpr)
            face.setPixmap(pix)
        else:
            face.setText("(ಠ_ಠ)" if alert else "(•_•)" if warn else "(•o•)" if running else "(•ᴗ•)")
        face.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        face.setStyleSheet("background: transparent; padding-bottom: 5px")
        lay.addWidget(face)
        color = t.red if alert else t.orange if warn else t.green if up else t.primary
        lay.addWidget(Text(parts[0], color, HEADLINE, True, wrap=True, center=True))
        if len(parts) > 1:
            lay.addWidget(Text(" · ".join(parts[1:]), t.secondary, center=True))
        hooks = self._hooks_line()
        if hooks and hooks[1]:
            lay.addWidget(Text(hooks[0], t.orange, bold=True, wrap=True, center=True))
        s = self.snap
        if s and not self.error and s.get("last_verdict"):
            p = s["last_verdict"]
            stale = p.get("stale_account") is True
            bits = [Text(L("Last probe"), t.tertiary, elide=False), Text("·", t.tertiary, elide=False),
                    Text(L("Unverified") if stale else word(p), t.secondary if stale else tint(p, t), bold=True, elide=False)]
            if ago(p.get("finished_ago")):
                bits += [Text("·", t.tertiary, elide=False), Text(ago(p.get("finished_ago")), t.tertiary, elide=False)]
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(4)
            rl.addStretch(1)
            for b in bits:
                rl.addWidget(b)
            rl.addStretch(1)
            lay.addWidget(row)
        quiet = self._quiet_lines()
        if quiet:
            lay.addWidget(Text(" · ".join(quiet), t.tertiary, wrap=True, center=True))
        if self.ctl.demo:
            lay.addWidget(Text("演示模式 · 离线样例数据" if _TABLE else "Demo · offline sample data", t.orange, center=True))
        return w

    def _quiet_lines(self) -> list[str]:
        s = self.snap
        if not s or self.error:
            return []
        out: list[str] = []
        acct = (s.get("account") or {}).get("label")
        if acct:
            out.append(L(acct) if (s.get("config") or {}).get("hide_titles") else acct)
        h = self._hooks_line()
        if h and not h[1]:
            out.append(h[0])
        sw = ago((s.get("account") or {}).get("switched_ago"))
        if sw:
            out.append(L("account switched %@", sw))
        out.append(self.ctl._target_text())
        return out

    def _hooks_line(self) -> tuple[str, bool] | None:
        s = self.snap
        if not s or self.error:
            return None
        h = s.get("hooks")
        if not h:
            a = ago(s.get("hooks_last_event_ago"))
            return (L("hooks alive %@", a), False) if a else (L("no hook events yet"), False)
        state = h.get("state")
        if state == "untrusted":
            return L("Hooks not trusted by Codex · run nerfed hooks trust"), True
        if state == "missing":
            return L("Codex does not list the plugin's hooks · run install.sh"), True
        if state != "trusted" and h.get("error"):
            return L("Codex could not list the hooks · run nerfed doctor"), True
        if (h.get("disabled") or 0) > 0:
            return L("Hooks switched off in Codex · turn them on in Codex's Hooks screen"), True
        if h.get("desktop_loaded") is not True:
            return L("Codex has not loaded the plugin yet · quit and reopen Codex"), True
        if h.get("desktop_loaded_current") is not True and (h.get("stale_since_install_s") or 0) > 240:
            return L("Codex still runs the previous version · quit and reopen Codex"), True
        return L("hooks alive %@", ago(h.get("last_desktop_event_ago")) or L("just now")), False

    # ---- setup

    def _setup(self) -> QWidget | None:
        s = self.snap
        if not s or self.error or not s.get("install"):
            return None
        inst = s["install"]
        installing = "setup" in self.ctl.backend.busy
        if inst.get("codex_found") is False:
            text, button, act = L("Codex is not installed on this Mac. Install the Codex app, then reopen this panel.").replace(
                "Mac", "computer").replace("这台 Mac", "这台电脑"), None, None
        elif inst.get("plugin_enabled") is False:
            text, button, act = (L("The plugin is not registered with Codex yet. Install adds the bundled plugin and records hook trust."),
                                 L("Install"), self.ctl.install_plugin)
        elif (s.get("hooks") or {}).get("state") == "untrusted":
            text, button, act = (L("Codex has not been told to trust the plugin's hooks, so nothing runs in your sessions yet."),
                                 L("Trust hooks"), self.ctl.trust_hooks)
        else:
            return None
        t = self.theme
        g = Group(L("Setup"), t)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 8, 10, 8)
        rl.setSpacing(10)
        rl.addWidget(Dot(t.orange))
        rl.addWidget(Text(text, t.secondary, wrap=True), 1)
        if installing:
            rl.addWidget(Text("…", t.secondary, elide=False))
        elif button and act:
            b = RowButton(button, t, act)
            b.setEnabled(not self.ctl.demo)
            rl.addWidget(b)
        g.add(row)
        return g

    # ---- threads

    def _threads(self) -> QWidget:
        t = self.theme
        threads = (self.snap or {}).get("threads") or []
        g = Group(L("Active sessions"), t, L("%@ in 48 h", len(threads)) if threads else None)
        if not threads:
            msg = L("Reading the ledger…") if self.snap is None else L("No Codex sessions in the last 48 hours.")
            lab = Text(msg, t.secondary, center=True, elide=False)
            lab.setMinimumHeight(40)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            g.add(lab)
            return g
        inner = QWidget()
        inner.setStyleSheet("background: transparent")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)
        for i, th in enumerate(threads):
            if i:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background: {Theme.css(t.sep)}; margin-left: 10px")
                il.addWidget(sep)
            il.addWidget(self._thread_row(th))
        self._list = QScrollArea()
        self._list.setWidget(inner)
        self._list.setWidgetResizable(True)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent }"
                                  " QScrollBar:vertical { width: 6px; background: transparent }"
                                  f" QScrollBar::handle:vertical {{ background: {Theme.css(t.tertiary)}; border-radius: 3px; min-height: 24px }}"
                                  " QScrollBar::add-line, QScrollBar::sub-line { height: 0 }")
        inner.setFixedWidth(WIDTH - 24)
        inner.adjustSize()
        cap = 340 if self.open is None else 460
        self._list.setFixedHeight(min(cap, max(inner.sizeHint().height(), 56)))
        value = self._scroll_value
        QTimer.singleShot(0, lambda s=self._list: s.verticalScrollBar().setValue(value))
        g.add(self._list)
        return g

    def _thread_row(self, th: dict) -> QWidget:
        t = self.theme
        tid = th.get("id", "")
        history = th.get("probes") or ([th["last_probe"]] if th.get("last_probe") else [])
        evidence = th.get("evidence") or []
        failure = th.get("last_failure")
        is_open = self.open == tid
        running = bool(th.get("probe_running")) or tid in self.ctl.pending_probes or ("probe:" + tid) in self.ctl.backend.busy
        row = ExpandableRow(bool(history or evidence or failure), lambda: self._toggle(tid), t)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        left = QHBoxLayout()
        left.setSpacing(8)
        lp = th.get("last_probe") or {}
        dot = (t.red if th.get("alert") else t.orange if th.get("suspicious") else t.green if th.get("upgraded")
               else t.tertiary if th.get("unverified") else t.green if lp.get("verdict") == "MATCH" else t.tertiary)
        d = Dot(dot)
        left.addWidget(d, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        cfg = (self.snap or {}).get("config") or {}
        title = th.get("title") or tid
        if cfg.get("hide_titles") and re.match(r"^Session \d+$", title):
            title = L("Session %@", title[8:])
        elif (self.snap or {}).get("demo"):
            title = L(title)
        col.addWidget(Text(title, t.primary, TITLE, True))
        if is_open:
            col.addWidget(report_lines(history, evidence, failure, t))
        else:
            col.addWidget(Text(self._meta(th), t.secondary))
            if running:
                note = th.get("probe_note")
                col.addWidget(Text(L("Probing · %@…", B(note)) if note else L("Probing, ephemeral forks in flight…"), t.secondary))
            elif th.get("last_probe"):
                col.addWidget(verdict_line(th["last_probe"], t))
            else:
                col.addWidget(Text(L("No probe yet · due") if th.get("due") else L("No probe yet"), t.tertiary))
            sev = th.get("last_evidence_severity")
            if th.get("last_evidence") and sev:
                color = t.red if sev == "hard" else t.orange if sev == "soft" else t.green
                ev = Text(evidence_text(th["last_evidence"], th.get("last_evidence_ago"), True), color)
                ev.setToolTip(L("Codex's own records show a switch to a better model (a rollout). Good news, still in effect. Click the row for the history.")
                              if sev == "good" else
                              L("Found in the session's own records, independent of any probe, and still in effect. Click the row for the history.")
                              if sev == "hard" else
                              L("Applied through the session's settings and still in effect: either you changed it, or Codex did (it lowers effort automatically at usage limits). Click the row for the history."))
                col.addWidget(ev)
        left.addLayout(col, 1)
        lay.addLayout(left, 1)
        # the dot sits on the title's first line
        left.setContentsMargins(0, 0, 0, 0)
        d.setFixedSize(7, QFontMetrics(font(TITLE, True)).height() // 2 + 4)
        if not running:
            if th.get("halted"):
                b = RowButton(L("Resume"), t, lambda: self.ctl.resume_thread(tid), destructive=True)
                b.setToolTip(L("Clear the halt (work tools are denied in this session)"))
            else:
                retry = (failure or {}).get("retryable") is True
                b = RowButton(L("Retry") if retry else L("Probe"), t, lambda: self.ctl.probe_thread(tid))
                b.setToolTip(L("Fork this session ephemerally (3 parallel forks) and fingerprint the answering model"))
            b.setEnabled(not self.ctl.demo)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)

        def menu(m: QMenu) -> None:
            if not running and not th.get("halted") and not self.ctl.demo:
                m.addAction(L("Retry the probe") if (failure or {}).get("retryable") else L("Probe now"),
                            lambda: self.ctl.probe_thread(tid))
            if th.get("report_text"):
                m.addAction(L("Copy report"), lambda: self.ctl.copy_text(report_copy(str(th["report_text"]), th.get("title") or "", title)))
            cwd = th.get("cwd") or ""
            if cwd and Path(cwd).is_dir():
                m.addAction(L("Open folder in Finder").replace("Finder", self._file_manager()).replace(
                    "在 Finder 中", "在" + self._file_manager() + "中"), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(cwd)))
            m.addAction("在详细窗口中打开" if _TABLE else "Open in inspector", lambda: self.ctl.open_inspector(tid))
        row.menu_builder = menu
        return row

    @staticmethod
    def _file_manager() -> str:
        if sys.platform == "win32":
            return "资源管理器" if _TABLE else "Explorer"
        return "文件管理器" if _TABLE else "file manager"

    @staticmethod
    def _meta(th: dict) -> str:
        parts = [f"{th.get('model') or '?'}" + (f" @ {th['effort']}" if th.get("effort") else "")]
        n = th.get("turns") or 0
        if n > 0:
            parts.append(L("1 turn") if n == 1 else L("%@ turns", n))
        if th.get("halted"):
            parts.append(L("halted"))
        a = ago(th.get("updated_ago"))
        if a:
            parts.append(L("active %@", a))
        return " · ".join(parts)

    # ---- fresh session

    def _fresh(self) -> QWidget:
        t = self.theme
        s = self.snap or {}
        running = bool(s.get("global_running")) or bool(self.ctl.pending_fresh_at) or "fresh" in self.ctl.backend.busy
        last = s.get("global_probe")
        failure = s.get("global_failure")
        model = s.get("default_model") or L("default model")
        effort = f" @ {s['default_effort']}" if s.get("default_effort") else ""
        g = Group(L("Fresh session"), t, model + effort)
        history = s.get("global_probes") or ([last] if last else [])
        row = ExpandableRow(bool(history or failure), lambda: self._toggle("fresh"), t)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(8)
        dot = t.tertiary if not last or is_failure(last) or last.get("stale_account") else tint(last, t)
        lay.addWidget(Dot(dot), 0, Qt.AlignmentFlag.AlignVCenter if self.open != "fresh" else Qt.AlignmentFlag.AlignTop)
        if self.open == "fresh":
            body = report_lines(history, [], failure, t)
        elif running:
            body = Text(L("Probing %@ new ephemeral sessions…", (s.get("config") or {}).get("queries", 3)), t.secondary)
        elif last:
            body = verdict_line(last, t)
        else:
            body = Text(L("Never probed · a brand-new session, no history"), t.secondary)
        lay.addWidget(body, 1)
        if not running:
            retry = (failure or {}).get("retryable") is True
            b = RowButton(L("Retry") if retry else L("Probe"), t, self.ctl.probe_fresh)
            b.setToolTip(L("Start brand-new ephemeral sessions and fingerprint what a new session gets"))
            b.setEnabled(not self.ctl.demo)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)

        def menu(m: QMenu) -> None:
            if not running and not self.ctl.demo:
                m.addAction(L("Retry the probe") if (failure or {}).get("retryable") else L("Probe now"), self.ctl.probe_fresh)
            if s.get("global_report_text"):
                m.addAction(L("Copy report"), lambda: self.ctl.copy_text(
                    report_copy(str(s["global_report_text"]), "Fresh session", L("Fresh session"))))
        row.menu_builder = menu
        g.add(row)
        return g

    # ---- footer

    def _footer(self) -> QWidget:
        t = self.theme
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(16)
        lay.addWidget(TextButton(L("Done") if self.show_settings else L("Settings"), t.secondary, self._toggle_settings))
        lay.addWidget(TextButton("详细窗口" if _TABLE else "Inspector", t.secondary, lambda: self.ctl.open_inspector(None)))
        lay.addStretch(1)
        s = self.snap or {}
        u = s.get("update") or {}
        if u.get("available") is True and u.get("latest"):
            # No self-updater on Windows/Linux: open the release page instead.
            lay.addWidget(TextButton(L("v%@ is out", u["latest"]), t.primary,
                                     lambda: QDesktopServices.openUrl(QUrl(u.get("url") or "https://github.com/MizuIro-H/is-gpt-nerfed-port/releases"))))
        elif s.get("version"):
            lay.addWidget(Text("v" + str(s["version"]) + (L(" · sample data") if s.get("demo") else ""), t.tertiary, elide=False))
        lay.addWidget(TextButton(L("Quit"), t.secondary, self.ctl.explicit_exit))
        return w

    def _toggle_settings(self) -> None:
        self.show_settings = not self.show_settings
        self.rebuild()

    # ---- settings (SettingsView.swift)

    def _settings(self) -> QWidget:
        t = self.theme
        cfg = (self.snap or {}).get("config") or {}
        ready = bool(cfg) and not self.ctl.demo
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        def row(title: str, control: QWidget, always: bool = False) -> QWidget:
            r = QWidget()
            rl = QHBoxLayout(r)
            rl.setContentsMargins(10, 6, 10, 6)
            rl.setSpacing(8)
            rl.addWidget(Text(title, t.primary), 1)
            if not always:
                control.setEnabled(ready and control.isEnabled())
            rl.addWidget(control, 0)
            return r

        def picker(key: str, current: str, options: list[tuple[str, str]]) -> QComboBox:
            c = QComboBox()
            c.setFont(font(TEXT))
            c.setFixedWidth(180)
            for value, label in options:
                c.addItem(label, value)
            if c.findData(current) < 0:
                c.addItem(current, current)
            c.setCurrentIndex(c.findData(current))
            c.currentIndexChanged.connect(lambda _i: self.ctl.set_config(key, str(c.currentData())))
            return c

        def toggle(key: str, value: bool) -> Switch:
            sw = Switch(value, t)
            sw.toggled.connect(lambda on: self.ctl.set_config(key, "true" if on else "false"))
            return sw

        freqs = [("manual", L("Manually")), ("turns:4", L("Every 4 turns")), ("turns:8", L("Every 8 turns")),
                 ("turns:16", L("Every 16 turns")), ("15m", L("Every 15 min of activity")),
                 ("30m", L("Every 30 min of activity")), ("1h", L("Every hour of activity")),
                 ("2h", L("Every 2 hours of activity"))]
        beats = [("manual", L("Manually")), ("15m", L("Every 15 minutes")), ("30m", L("Every 30 minutes")),
                 ("1h", L("Every hour")), ("2h", L("Every 2 hours")), ("6h", L("Every 6 hours"))]
        modes = [("auto", L("Probe in the background")), ("nudge", L("Only remind me"))]
        confs = [(0.7, "70%"), (0.8, "80%"), (0.9, "90%"), (0.95, "95%")]

        g = Group(L("Schedule"), t)
        g.add(row(L("Probe each active session"), picker("frequency", str(cfg.get("frequency", "30m")), freqs)))
        g.add(row(L("Fresh-session heartbeat"), picker("fresh_frequency", str(cfg.get("fresh_frequency", "manual")), beats)))
        g.add(row(L("When a probe is due"), picker("mode", str(cfg.get("mode", "auto")), modes)))
        seg = Segments(["1", "2", "3"], str(cfg.get("queries", 3)), t)
        seg.changed.connect(lambda v: self.ctl.set_config("queries", v))
        g.add(row(L("Forks per probe"), seg))
        g.add(row(L("Run the forks in parallel"), toggle("parallel", bool(cfg.get("parallel", True)))))
        lay.addWidget(g)

        g = Group(L("Verdict"), t)
        mc = float(cfg.get("mismatch_confidence", 0.8) or 0.8)
        seg = Segments([c[1] for c in confs], min(confs, key=lambda c: abs(c[0] - mc))[1], t)
        seg.changed.connect(lambda v: self.ctl.set_config("mismatch_confidence", str(dict((b, a) for a, b in confs)[v])))
        g.add(row(L("Call a mismatch at"), seg))
        g.add(row(L("Halt the session after a mismatch"), toggle("halt_on_mismatch", bool(cfg.get("halt_on_mismatch", False)))))
        g.add(row(L("Scan rollouts on every turn"), toggle("passive", bool(cfg.get("passive", True)))))
        lay.addWidget(g)

        g = Group(L("Alerts"), t)
        g.add(row(L("Notifications"), toggle("notify", bool(cfg.get("notify", True)))))
        g.add(row(L("Also notify on a match"), toggle("notify_on_ok", bool(cfg.get("notify_on_ok", False)))))
        g.add(row(L("Post matches into the session"), toggle("announce_ok", bool(cfg.get("announce_ok", False)))))
        g.add(row(L("Sound on a downgrade"), toggle("sound", bool(cfg.get("sound", True)))))
        lay.addWidget(g)

        g = Group(L("App"), t)
        g.add(row(L("Hide session titles and account (for screenshots)"), toggle("hide_titles", bool(cfg.get("hide_titles", False)))))
        g.add(row(L("Check for updates"), toggle("check_updates", bool(cfg.get("check_updates", False)))))
        login = Switch(self.ctl.autostart_enabled(), t)
        login.setEnabled(not self.ctl.demo)
        login.toggled.connect(self.ctl.set_autostart)
        g.add(row(L("Launch at login"), login, always=True))
        target = RowButton(self.ctl._target_text() + " …", t, self.ctl.settings)
        target.setEnabled(not self.ctl.demo)
        g.add(row("Codex 目标" if _TABLE else "Codex target", target, always=True))
        lay.addWidget(g)
        return w
