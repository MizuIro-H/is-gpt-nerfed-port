from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import shutil
import time
import tomllib
from pathlib import Path

exe = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
fake = Path(sys.argv[3]).resolve()
tmp = Path(tempfile.mkdtemp(prefix="is-gpt-nerfed-frozen-smoke-"))
try:
    env = os.environ.copy()
    env["NERFED_PLUGIN_ROOT"] = str(root / "plugin")
    env["NERFED_CORE_BIN"] = str(exe)
    env["CODEX_BIN"] = str(fake)
    env["CODEX_HOME"] = str(tmp / "codex-home")
    env["NERFED_HOME"] = str(tmp / "nerfed-home")
    Path(env["CODEX_HOME"]).mkdir(parents=True)
    env["NERFED_NO_UPDATE_CHECK"] = "1"
    trust_file = tmp / "fake-trust.json"
    trust_file.write_text(json.dumps([f"sha256:fake-{event}" for event in
                                      ("preToolUse", "sessionStart", "sessionEnd", "userPromptSubmit", "stop")]), encoding="utf-8")

    def run(*args: str, extra_env: dict[str, str] | None = None) -> str:
        call_env = env | (extra_env or {})
        result = subprocess.run([str(exe), *args], env=call_env, text=True, encoding="utf-8", errors="replace",
                                capture_output=True, check=False, timeout=90)
        if result.returncode:
            raise RuntimeError(f"{[str(exe), *args]} exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
        return result.stdout

    assert "0.5.3" in run("--version")
    marketplace = json.loads((root / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
    assert marketplace["plugins"][0]["source"]["path"] == "./plugin"
    assert (root / "plugin" / ".codex-plugin" / "plugin.json").is_file()
    snapshot = json.loads(run("snapshot", "--demo", "--json"))
    assert snapshot.get("version") == "0.5.3", snapshot.get("version")
    assert "PASS" in run("selftest")
    run("config", "init")
    run("config", "set", "codex_bin", str(fake))
    run("setup", "--no-cli", "--no-trust",
        extra_env={"FAKE_CODEX_TRUST_FILE": str(trust_file), "CODEX_BIN": str(fake)})
    runtime = json.loads((tmp / "nerfed-home" / "runtime.json").read_text(encoding="utf-8"))
    assert runtime.get("command") == [str(exe)]
    assert Path(runtime.get("plugin_root", "")).resolve() == (root / "plugin").resolve()
    stable = tmp / "nerfed-home" / "plugin"
    assert (stable / "skills" / "is-gpt-nerfed" / "scripts" / "hook.ps1").is_file()
    assert (stable / ".codex-plugin" / "plugin.json").is_file()
    assert (tmp / "codex-home" / "config.toml").is_file()
    if os.name != "nt":
        assert (tmp / "nerfed-home" / "runtime.sh").is_file()
    config_doc = tomllib.loads((tmp / "codex-home" / "config.toml").read_text(encoding="utf-8"))
    assert config_doc["marketplaces"]["is-gpt-nerfed"]["source"] == str(root)
    assert config_doc["plugins"]["is-gpt-nerfed@is-gpt-nerfed"]["enabled"] is True

    # Exercise the real hook entrypoint and runtime descriptor after setup. The
    # Chinese payload verifies UTF-8 stdin in PowerShell as well as core parsing.
    hook_env = env.copy()
    hook_env.pop("NERFED_CORE_BIN", None)
    hook_env.pop("NERFED_PLUGIN_ROOT", None)
    hook_env["PLUGIN_ROOT"] = str(tmp / "nerfed-home" / "plugin")
    payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "hook-smoke",
                          "prompt": "你好桌面"}, ensure_ascii=False)
    if os.name == "nt":
        manifest = json.loads((root / "plugin" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        command = manifest["hooks"]["hooks"]["UserPromptSubmit"][0]["hooks"][0]["commandWindows"]
        comspec = hook_env.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        # Pass one raw command line exactly like Codex's cmd /C wrapper; a
        # Python argv list would add Windows backslash escaping to the nested PS quotes.
        hook_cmd = f'"{comspec}" /C "{command}"'
    else:
        hook_cmd = ["sh", str(root / "plugin" / "skills" / "is-gpt-nerfed" / "scripts" / "hook.sh"),
                    "UserPromptSubmit"]
    hook = subprocess.run(hook_cmd, env=hook_env, input=payload, text=True, encoding="utf-8",
                          capture_output=True, timeout=30)
    assert hook.returncode == 0, hook.stderr
    rows = [json.loads(line) for line in (tmp / "nerfed-home" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(row.get("event") == "UserPromptSubmit" and row.get("sid") == "hook-smoke"
               and row.get("prompt_chars") == 4 for row in rows), rows

    thread = "packaging-worker-smoke"
    run("worker", "--thread", thread, "--queries", "3", "--detach",
        extra_env={"FAKE_CODEX_MODEL": "gpt-6-astra", "FAKE_CODEX_TRUST_FILE": str(trust_file)})
    completed = None
    for _ in range(90):
        for path in (tmp / "nerfed-home" / "probes").glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("thread_id") == thread and record.get("status") != "running":
                completed = record
                break
        if completed:
            break
        time.sleep(0.5)
    if not completed:
        for path in sorted((tmp / "nerfed-home").rglob("*")):
            if path.is_file() and path.stat().st_size < 200_000:
                print(f"--- {path.relative_to(tmp)} ---", file=sys.stderr)
                print(path.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
    assert completed and completed.get("verdict") == "MATCH", completed
    print(f"frozen core smoke passed: {exe} (version, snapshot, selftest, setup/runtime, UTF-8 hook, detached offline fork MATCH)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
