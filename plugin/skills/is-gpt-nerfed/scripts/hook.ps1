param([Parameter(Mandatory=$true)][string]$Event)
$ErrorActionPreference = 'SilentlyContinue'
$codexHome = $env:CODEX_HOME
if (-not $codexHome) { $codexHome = Join-Path $env:USERPROFILE '.codex' }
$nerfedHome = $env:NERFED_HOME
if (-not $nerfedHome) { $nerfedHome = Join-Path $codexHome 'is-gpt-nerfed' }
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

function Invoke-HookCommand([string[]]$Command, [AllowNull()][string]$Payload, [switch]$AppendHookArgs = $true) {
    if (-not $Command) { return }
    $executable = $Command[0]
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        $resolved = Get-Command $executable -ErrorAction SilentlyContinue
        if (-not $resolved) { return }
        $executable = $resolved.Source
    }
    if (-not $PSBoundParameters.ContainsKey('Payload')) { $Payload = [Console]::In.ReadToEnd() }
    $tail = @()
    if ($Command.Count -gt 1) { $tail = $Command[1..($Command.Count - 1)] }
    if ($AppendHookArgs) { $tail += @('hook', '--event', $Event) }
    $quote = {
        param([string]$value)
        if ($value -notmatch '[\s"]') { return $value }
        $value = [regex]::Replace($value, '(\\*)"', { param($m) $m.Groups[1].Value + $m.Groups[1].Value + '\"' })
        $value = [regex]::Replace($value, '(\\+)$', { param($m) $m.Groups[1].Value + $m.Groups[1].Value })
        return '"' + $value + '"'
    }
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $executable
    $start.Arguments = (($tail | ForEach-Object { & $quote ([string]$_) }) -join ' ')
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = $utf8
    $start.StandardErrorEncoding = $utf8
    $start.EnvironmentVariables['PYTHONUTF8'] = '1'
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { return }
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    if ($Payload) {
        $bytes = $utf8.GetBytes($Payload)
        $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
        $process.StandardInput.BaseStream.Flush()
    }
    $process.StandardInput.Close()
    $process.WaitForExit()
    [Console]::Out.Write($stdout.Result)
    [Console]::Error.Write($stderr.Result)
}

# The Windows desktop may share its CODEX_HOME with a WSL distro. Run the Linux
# hook there so both clients use one ledger and the POSIX backend paths stay native.
if ($codexHome.StartsWith('\\wsl.localhost\', [StringComparison]::OrdinalIgnoreCase) -or
    $codexHome.StartsWith('\\wsl$\', [StringComparison]::OrdinalIgnoreCase)) {
    $uncParts = $codexHome.TrimStart([char]'\').Split([char]'\')
    if ($uncParts.Count -lt 3) { exit 0 }
    $distro = $uncParts[1]
    $linuxCodexHome = '/' + (($uncParts[2..($uncParts.Count - 1)] -join '/') -replace '\\','/')
    $linuxHook = "$linuxCodexHome/is-gpt-nerfed/plugin/skills/is-gpt-nerfed/scripts/hook.sh"
    $wslCommand = 'CODEX_HOME="$1" NERFED_HOME="$2" exec bash "$3" "$4"'
    [Console]::OutputEncoding = $utf8
    $payload = [Console]::In.ReadToEnd()
    Invoke-HookCommand -Command @('wsl.exe', '-d', $distro, '--exec', 'bash', '-c', $wslCommand,
                                  'nerfed-hook', $linuxCodexHome, "$linuxCodexHome/is-gpt-nerfed", $linuxHook, $Event) `
                       -Payload $payload -AppendHookArgs:$false
    exit 0
}

$pluginRoot = $env:NERFED_PLUGIN_ROOT
if (-not $pluginRoot) { $pluginRoot = $env:PLUGIN_ROOT }
if (-not $pluginRoot) { $pluginRoot = Join-Path $nerfedHome 'plugin' }
$env:NERFED_PLUGIN_ROOT = $pluginRoot
$core = $env:NERFED_CORE_BIN
if (-not $core) {
    $candidate = Join-Path (Split-Path -Parent $pluginRoot) 'nerfed-core.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $core = $candidate }
}
if ($core -and (Test-Path -LiteralPath $core -PathType Leaf)) {
    Invoke-HookCommand @($core)
    exit 0
}
$runtime = Join-Path $nerfedHome 'runtime.json'
if (Test-Path -LiteralPath $runtime -PathType Leaf) {
    try {
        $cfg = Get-Content -LiteralPath $runtime -Raw -Encoding UTF8 | ConvertFrom-Json
        $cmd = @($cfg.command | ForEach-Object { [string]$_ })
        if ($cfg.plugin_root) { $env:NERFED_PLUGIN_ROOT = [string]$cfg.plugin_root }
        if ($cmd.Count -ge 1) {
            Invoke-HookCommand $cmd
            exit 0
        }
    } catch {}
}
$source = Join-Path $pluginRoot 'skills\is-gpt-nerfed\scripts\nerfed'
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if ($python -and (Test-Path -LiteralPath $source -PathType Leaf)) {
    Invoke-HookCommand @($python.Source, $source)
}
exit 0
