param(
    [string]$LinuxCoreArchive = (Join-Path $PSScriptRoot "..\Linux\dist\nerfed-core-linux-x86_64.tar.gz")
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if (-not $IsWindows -and $env:OS -ne "Windows_NT") { throw "Run this script in native Windows PowerShell or PowerShell 7." }
if (-not (Test-Path $LinuxCoreArchive)) { throw "Missing Jammy-built WSL core archive: $LinuxCoreArchive. Run packaging/build_linux_docker.sh first." }

$Build = Join-Path $Root ".build\windows"
$UvDir = Join-Path $Root ".build\uv-windows"
$UvExe = Join-Path $UvDir "uv.exe"
$PythonInstall = Join-Path $Root ".build\uv-python-windows"
$Venv = Join-Path $Build "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$env:UV_PYTHON_INSTALL_DIR = $PythonInstall
$env:UV_CACHE_DIR = Join-Path $Root ".build\uv-cache-windows"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $Root ".build\pyinstaller-cache-windows"

function Quote-ProcessArgument([string]$Value) {
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $Builder = New-Object System.Text.StringBuilder
    [void]$Builder.Append('"')
    $Slashes = 0
    foreach ($Character in $Value.ToCharArray()) {
        if ($Character -eq '\') { $Slashes++; continue }
        if ($Character -eq '"') {
            [void]$Builder.Append(('\' * (2 * $Slashes + 1))).Append('"')
        } else {
            [void]$Builder.Append(('\' * $Slashes)).Append($Character)
        }
        $Slashes = 0
    }
    [void]$Builder.Append(('\' * (2 * $Slashes))).Append('"')
    return $Builder.ToString()
}

function Invoke-Checked([string]$Step, [string]$FilePath, [string[]]$Arguments) {
    $LogDir = Join-Path $Build "logs"
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $SafeName = $Step -replace '[^A-Za-z0-9_-]', '_'
    $OutLog = Join-Path $LogDir "$SafeName.stdout.log"
    $ErrLog = Join-Path $LogDir "$SafeName.stderr.log"
    $Start = New-Object System.Diagnostics.ProcessStartInfo
    $Start.FileName = $FilePath
    $Start.Arguments = (($Arguments | ForEach-Object { Quote-ProcessArgument ([string]$_) }) -join ' ')
    $Start.WorkingDirectory = $Root
    $Start.UseShellExecute = $false
    $Start.CreateNoWindow = $true
    $Start.RedirectStandardOutput = $true
    $Start.RedirectStandardError = $true
    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $Start
    if (-not $Process.Start()) { throw "$Step could not start: $FilePath" }
    $StdoutTask = $Process.StandardOutput.ReadToEndAsync()
    $StderrTask = $Process.StandardError.ReadToEndAsync()
    $Process.WaitForExit()
    $StdoutTask.Result | Set-Content -Encoding utf8 $OutLog
    $StderrTask.Result | Set-Content -Encoding utf8 $ErrLog
    if ($Process.ExitCode -ne 0) {
        Get-Content $ErrLog -Tail 80
        throw "$Step failed with exit code $($Process.ExitCode); logs: $ErrLog"
    }
}

if (-not (Test-Path $UvExe)) {
    New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
    $Archive = Join-Path $Root ".build\uv-windows.zip"
    Invoke-WebRequest -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $Archive
    Expand-Archive -Path $Archive -DestinationPath (Join-Path $UvDir "expanded") -Force
    $FoundUv = Get-ChildItem (Join-Path $UvDir "expanded") -Filter uv.exe -Recurse | Select-Object -First 1
    if (-not $FoundUv) { throw "The downloaded uv archive did not contain uv.exe." }
    Copy-Item $FoundUv.FullName $UvExe
}

New-Item -ItemType Directory -Force -Path $Build | Out-Null
Invoke-Checked "uv Python install" $UvExe @("python", "install", "3.12")
$ManagedPython = Get-ChildItem $PythonInstall -Directory -Filter "cpython-3.12.*-windows-x86_64-none" |
    Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName "python.exe" } |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ManagedPython) { throw "uv did not provide its managed Python 3.12 under $PythonInstall" }
if (-not (Test-Path $VenvPython)) {
    Invoke-Checked "uv venv" $UvExe @("venv", "--python", $ManagedPython, $Venv)
}
Invoke-Checked "uv dependencies" $UvExe @("pip", "install", "--python", $VenvPython, "-r", (Join-Path $Root "requirements-build.txt"))

Invoke-Checked "PyInstaller GUI build" $VenvPython @("-m", "PyInstaller", "--clean", "--noconfirm", "--workpath", (Join-Path $Build "pyinstaller-work"), "--distpath", (Join-Path $Build "pyinstaller-dist"), "packaging/IsGPTNerfed.spec")
Invoke-Checked "PyInstaller core build" $VenvPython @("-m", "PyInstaller", "--clean", "--noconfirm", "--workpath", (Join-Path $Build "pyinstaller-work"), "--distpath", (Join-Path $Build "pyinstaller-dist"), "packaging/IsGPTNerfed-core.spec")
Invoke-Checked "PyInstaller fake appserver build" $VenvPython @("-m", "PyInstaller", "--clean", "--noconfirm", "--onefile", "--name", "fake_codex", "--add-data", "tests/fixtures;fixtures", "--distpath", (Join-Path $Build "fake-dist"), "--workpath", (Join-Path $Build "fake-work"), "tests/fake_codex.py")
$env:NERFED_TEST_CODEX_BIN = Join-Path $Build "fake-dist\fake_codex.exe"
Invoke-Checked "Windows unittest suite" $VenvPython @("-m", "unittest", "discover", "-s", "tests", "-v")
Remove-Item Env:\NERFED_TEST_CODEX_BIN

$Stage = Join-Path $Build "stage"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
Copy-Item (Join-Path $Build "pyinstaller-dist\IsGPTNerfed\*") $Stage -Recurse -Force
Copy-Item (Join-Path $Build "pyinstaller-dist\nerfed-core.exe") (Join-Path $Stage "nerfed-core.exe") -Force
Copy-Item (Join-Path $Root "plugin") (Join-Path $Stage "plugin") -Recurse -Force
Copy-Item (Join-Path $Root ".agents") (Join-Path $Stage ".agents") -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "wsl") | Out-Null
Copy-Item $LinuxCoreArchive (Join-Path $Stage "wsl\nerfed-core-linux.tar.gz") -Force
Invoke-Checked "Frozen Windows GUI smoke" $VenvPython @("packaging/gui_smoke.py", (Join-Path $Stage "IsGPTNerfed.exe"))
Invoke-Checked "Frozen Windows core smoke" $VenvPython @("packaging/smoke.py", (Join-Path $Stage "nerfed-core.exe"), $Stage, (Join-Path $Build "fake-dist\fake_codex.exe"))
Invoke-Checked "Windows license collection" $VenvPython @("packaging/copy_licenses.py", $Venv, (Join-Path $Stage "licenses"))
Copy-Item packaging/NOTICE (Join-Path $Stage "NOTICE")
Copy-Item README-CROSSPLATFORM.md (Join-Path $Stage "README-CROSSPLATFORM.md")

$Archive = Join-Path $Root "Windows\dist\IsGPTNerfed-0.5.3-windows-x64.zip"
if (Test-Path $Archive) { Remove-Item $Archive -Force }
Invoke-Checked "Windows ZIP creation" $VenvPython @("packaging/create_zip.py", $Stage, $Archive)
$null = [Reflection.Assembly]::LoadWithPartialName("System.IO.Compression")
$null = [Reflection.Assembly]::LoadWithPartialName("System.IO.Compression.FileSystem")
$ZipCheck = [System.IO.Compression.ZipFile]::OpenRead($Archive)
try {
    $Names = @($ZipCheck.Entries | ForEach-Object { $_.FullName })
    foreach ($Required in @(".agents/plugins/marketplace.json", "plugin/.codex-plugin/plugin.json",
                            "wsl/nerfed-core-linux.tar.gz", "nerfed-core.exe", "IsGPTNerfed.exe")) {
        if ($Names -notcontains $Required) { throw "Windows ZIP is missing required entry: $Required" }
    }
} finally { $ZipCheck.Dispose() }
$Hash = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Encoding ascii -NoNewline -Path "$Archive.sha256" -Value "$Hash  $(Split-Path $Archive -Leaf)`n"
Write-Output "Built $Archive using managed Python $(& $VenvPython --version)"
