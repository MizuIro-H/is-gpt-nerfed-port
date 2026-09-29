from pathlib import Path
root = Path.cwd()
a = Analysis(
    [str(root / "desktop" / "cli_entry.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "plugin"), "plugin"), (str(root / "desktop"), "desktop")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="IsGPTNerfed", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="IsGPTNerfed", strip=False, upx=False)
