$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".veyra-local"
$statePath = Join-Path $runtimeRoot "state.json"
$powershellPath = (Get-Command powershell.exe -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    Write-Host "No launcher-owned Veyra processes are recorded." -ForegroundColor Yellow
    Write-Host "PostgreSQL was not stopped." -ForegroundColor Cyan
    exit 0
}

try { $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json }
catch { throw "The launcher state file is unreadable. No process was stopped." }

$stopped = @()
$alreadyExited = @()
$skipped = @()
foreach ($entry in @($state.processes)) {
    $pidValue = [int]$entry.pid
    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($null -eq $process) { $alreadyExited += [string]$entry.service; continue }

    $recordedProcessPath = [string]$entry.process_path
    if ([string]::IsNullOrWhiteSpace($recordedProcessPath)) { $recordedProcessPath = $powershellPath }
    $samePath = $process.Path -ieq $recordedProcessPath
    $recordedStart = [DateTime]::Parse(
        [string]$entry.started_at_utc,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind
    )
    $sameStartTime = [Math]::Abs(($process.StartTime.ToUniversalTime() - $recordedStart.ToUniversalTime()).TotalSeconds) -le 2
    $isPowerShell = $process.ProcessName -in @("powershell", "pwsh")
    $sameScript = $true
    if (-not [string]::IsNullOrWhiteSpace([string]$entry.script_path)) {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
        $sameScript = $null -ne $processInfo -and [string]$processInfo.CommandLine -match [regex]::Escape([string]$entry.script_path)
    }
    if (-not $samePath -or -not $sameStartTime -or -not $isPowerShell -or -not $sameScript) {
        $skipped += [string]$entry.service
        continue
    }

    & taskkill.exe /PID $pidValue /T /F 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0 -or $null -eq (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) { $stopped += [string]$entry.service }
    else { $skipped += [string]$entry.service }
}

Remove-Item -LiteralPath $statePath -Force
Write-Host "Veyra local shutdown summary" -ForegroundColor Cyan
Write-Host "----------------------------" -ForegroundColor Cyan
if ($stopped.Count -gt 0) { Write-Host "STOPPED: $($stopped -join ', ')" -ForegroundColor Green }
if ($alreadyExited.Count -gt 0) { Write-Host "ALREADY EXITED: $($alreadyExited -join ', ')" -ForegroundColor Yellow }
if ($skipped.Count -gt 0) { Write-Host "SKIPPED (ownership could not be verified): $($skipped -join ', ')" -ForegroundColor Red }
if ($stopped.Count -eq 0 -and $alreadyExited.Count -eq 0 -and $skipped.Count -eq 0) { Write-Host "No launcher-owned Veyra processes were running." -ForegroundColor Yellow }
Write-Host "PostgreSQL was not stopped." -ForegroundColor Cyan