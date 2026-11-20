"""Frozen-build check for the WinUI 3 inspector: it must reach its ready state and open a window.

A missing resources.pri (or any other startup failure) makes the process die before App.OnLaunched finishes,
which a "the exe exists" check never notices. The tray app talks to it over stdin/stdout, so do the same here.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path

exe = Path(sys.argv[1]).resolve()
STRINGS = {k: k for k in (
    "title refresh settings exit sessions fresh_tab plugin col_session col_model col_effort col_state col_evidence "
    "report_placeholder history_placeholder report history probe retry resume copy copied fresh_hint model_placeholder "
    "effort_placeholder fresh plugin_hint install trust status activity error_title demo empty").split()}
LONG_REPORT = "\n".join(f"Line {i}: ModelTrace fingerprint evidence detail" for i in range(60))
SAMPLE_THREADS = [
    {
        "id": "smoke-alert-1",
        "title": "中文会话 · 降级测试",
        "model": "gpt-6-astra",
        "effort": "high",
        "state": "降级",
        "evidence": "rollout model changed",
        "alert": True,
        "suspicious": False,
        "report": LONG_REPORT,
        "history": LONG_REPORT,
        "can_probe": True,
        "can_retry": False,
        "can_resume": True,
    },
    {
        "id": "smoke-warn-2",
        "title": "Suspicious session",
        "model": "gpt-6-sol",
        "effort": "medium",
        "state": "可疑",
        "evidence": "low confidence match",
        "alert": False,
        "suspicious": True,
        "report": "Sample report body",
        "history": "Sample history body",
        "can_probe": True,
        "can_retry": True,
        "can_resume": False,
    },
]

proc = subprocess.Popen([str(exe)], cwd=str(exe.parent), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
stdin, stdout, stderr = proc.stdin, proc.stdout, proc.stderr
assert stdin is not None and stdout is not None and stderr is not None
try:
    deadline = time.monotonic() + 30
    line = b""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"inspector exited {proc.returncode} before ready\n"
                             f"{stderr.read().decode('utf-8', 'replace')[-2000:]}")
        line = stdout.readline()
        if line.strip():
            break
    else:
        raise SystemExit("inspector did not answer within 30s")
    if json.loads(line) != {"action": "ready"}:
        raise SystemExit(f"unexpected first message: {line!r}")
    for message in ({"type": "init", "strings": STRINGS, "icon": str(exe.parent / "IsGPTNerfed.ico")},
                    {"type": "state", "status": "alert", "headline": "smoke · 1 downgraded", "substatus": "just now",
                     "demo": True, "threads": SAMPLE_THREADS, "fresh_enabled": True,
                     "global_report": LONG_REPORT, "plugin_status": "enabled: True",
                     "setup_enabled": True, "trust_enabled": True, "settings_enabled": True},
                    {"type": "show", "thread": "smoke-alert-1"},
                    {"type": "log", "text": "smoke log line 1\nsmoke log line 2"},
                    {"type": "error", "text": "smoke non-fatal notice"},
                    {"type": "state", "status": "ok", "headline": "smoke · updated", "substatus": "updated",
                     "demo": True, "threads": SAMPLE_THREADS, "fresh_enabled": True,
                     "global_report": "updated", "plugin_status": "enabled: True",
                     "setup_enabled": True, "trust_enabled": True, "settings_enabled": True}):
        stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        stdin.flush()
    time.sleep(5)
    if proc.poll() is not None:
        raise SystemExit(f"inspector exited {proc.returncode} after show\n"
                         f"{stderr.read().decode('utf-8', 'replace')[-2000:]}")
    # Closing stdin is how the tray app shuts it down; it must exit on its own.
    stdin.close()
    rc = proc.wait(timeout=15)
    err_text = stderr.read().decode("utf-8", "replace").strip()
    if rc != 0 or err_text:
        raise SystemExit(f"inspector did not exit cleanly on stdin close (rc={rc}): {err_text}")
finally:
    if proc.poll() is None:
        proc.kill()
print(f"WinUI inspector smoke passed: {exe}")
