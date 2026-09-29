# The core is intentionally a separate executable: GUI subprocess calls remain
# independent of PySide6 and work from WSL/headless environments.
from pathlib import Path
import ast
import importlib.util
import sys
root = Path.cwd()
script_dir = root / "plugin" / "skills" / "is-gpt-nerfed" / "scripts"
stdlib = set(sys.stdlib_module_names)
hidden = {"codex_appserver", "modeltrace_core", "simple_term_menu"}
for filename in [script_dir / "nerfed", script_dir / "codex_appserver.py", script_dir / "modeltrace_core.py"]:
    tree = ast.parse(filename.read_text(encoding="utf-8"), filename=str(filename))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
            for alias in node.names:
                child = node.module + "." + alias.name
                if child.split(".", 1)[0] in stdlib:
                    try:
                        if importlib.util.find_spec(child) is not None:
                            hidden.add(child)
                    except (ImportError, ModuleNotFoundError, ValueError):
                        pass
        else:
            continue
        hidden.update(name for name in names if name.split(".", 1)[0] in stdlib)
hidden.discard("fcntl" if sys.platform == "win32" else "msvcrt")
a = Analysis(
    [str(root / "packaging" / "core_entry.py")],
    pathex=[str(root), str(script_dir), str(script_dir / "vendor")],
    binaries=[],
    datas=[],
    hiddenimports=sorted(hidden),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "shiboken6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="nerfed-core", console=True, upx=False)
