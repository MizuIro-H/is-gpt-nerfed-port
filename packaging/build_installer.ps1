$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

# Wraps the already-built dist\windows (run build_windows.ps1 first) into
# dist\IsGPTNerfed-<ver>-windows-x64-setup.exe with Inno Setup. Inno Setup is fetched into .build\ once.
$Source = Join-Path $Root "dist\windows"
if (-not (Test-Path (Join-Path $Source "IsGPTNerfed.exe"))) { throw "dist\windows is missing; run packaging\build_windows.ps1 first." }
$Version = (Select-String -Path (Join-Path $Root "desktop\backend.py") -Pattern '^APP_VERSION = "(\d+\.\d+\.\d+)').Matches[0].Groups[1].Value

$Inno = Join-Path $Root ".build\innosetup"
$Iscc = Join-Path $Inno "ISCC.exe"
if (-not (Test-Path $Iscc)) {
    $SetupExe = Join-Path $Root ".build\innosetup-setup.exe"
    New-Item -ItemType Directory -Force (Split-Path $SetupExe) | Out-Null
    # Pinned: the script targets Inno Setup 6 syntax.
    Invoke-WebRequest -Uri "https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe" -OutFile $SetupExe
    if ((Get-FileHash $SetupExe -Algorithm SHA256).Hash -ne "A549929319F9120716677C685535CA4671E4B937B5FDC87E2585F32D8EB30E8C" -or
        (Get-AuthenticodeSignature $SetupExe).Status -ne "Valid") {
        throw "Inno Setup download does not match the pinned 6.7.4 installer."
    }
    # /PORTABLE=1: unpack into $Inno without registering an installation.
    $p = Start-Process $SetupExe -Wait -PassThru -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/PORTABLE=1", "/DIR=`"$Inno`""
    if ($p.ExitCode -ne 0 -or -not (Test-Path $Iscc)) { throw "Inno Setup install failed ($($p.ExitCode))" }
}
# Simplified Chinese ships only as an "unofficial" translation in the source tree, not in the installer.
$ZhIsl = Join-Path $Inno "Languages\ChineseSimplified.isl"
if (-not (Test-Path $ZhIsl)) {
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/jrsoftware/issrc/is-6_7_4/Files/Languages/Unofficial/ChineseSimplified.isl" -OutFile $ZhIsl
    if ((Get-FileHash $ZhIsl -Algorithm SHA256).Hash -ne "7D544B9BB1D142CFA11F2E5D3CC8ABE2E55F8E066C5124E3772675AA236E1278") {
        Remove-Item $ZhIsl; throw "ChineseSimplified.isl does not match the pinned 6.7.4 file."
    }
}

$Out = Join-Path $Root "dist"
& $Iscc "/Q" "/DAppVersion=$Version" "/DSourceDir=$Source" "/DOutputDir=$Out" (Join-Path $PSScriptRoot "IsGPTNerfed.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)" }
$Setup = Join-Path $Out "IsGPTNerfed-$Version-windows-x64-setup.exe"
$Hash = (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  $(Split-Path $Setup -Leaf)" | Set-Content -Encoding ascii "$Setup.sha256"
"Built $Setup ($([math]::Round((Get-Item $Setup).Length / 1MB)) MB)"
