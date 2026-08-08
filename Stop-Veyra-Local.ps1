$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".veyra-local"
$statePath = Join-Path $runtimeRoot "state.json"
$powershellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

function Get-ExecutionControllers {
    return @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -match "manage\.py\s+run_execution_layer" -and
            $_.ExecutablePath -eq $pythonPath
        })
}

function Test-VeyraFrontendProcess {
    param([object]$ProcessInfo)
    if ($null -eq $ProcessInfo) { return $false }
    $command = [string]$ProcessInfo.CommandLine
    $frontendRoot = Join-Path $projectRoot "frontend"
    $frontendLauncher = Join-Path $projectRoot "start-frontend.ps1"
    return (
        $ProcessInfo.Name -eq "node.exe" -and
        $command -match [regex]::Escape($frontendRoot) -and
        $command -match "next|start-server"
    ) -or (
        $ProcessInfo.Name -in @("powershell.exe", "pwsh.exe") -and
        $command -match [regex]::Escape($frontendLauncher)
    )
}

function Get-VeyraFrontendProcesses {
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { Test-VeyraFrontendProcess $_ })
}

function Stop-ProcessTreeIfPresent {
    param([int]$ProcessId)

    # The target may exit naturally after discovery but before taskkill starts.
    # With $ErrorActionPreference = "Stop", taskkill's harmless "not found"
    # stderr would otherwise abort the entire shutdown.
    if ($null -eq (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        return $true
    }

    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
        $exitCode = $LASTEXITCODE
    } catch {
        $exitCode = 1
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }

    return ($exitCode -eq 0 -or $null -eq (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue))
}

$stopped = @()
$alreadyExited = @()
$skipped = @()

if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    try { $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json }
    catch { throw "The launcher state file is unreadable. No process was stopped." }

    foreach ($entry in @($state.processes)) {
        $pidValue = [int]$entry.pid
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($null -eq $process) { $alreadyExited += [string]$entry.service; continue }

        # A launcher process can exit between Get-Process and property access.  Treat
        # that race as already-exited instead of aborting the entire shutdown.
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
        if ($null -eq $processInfo) {
            $alreadyExited += [string]$entry.service
            continue
        }

        $recordedProcessPath = [string]$entry.process_path
        if ([string]::IsNullOrWhiteSpace($recordedProcessPath)) { $recordedProcessPath = $powershellPath }

        $actualProcessPath = [string]$processInfo.ExecutablePath
        if ([string]::IsNullOrWhiteSpace($actualProcessPath)) {
            try { $actualProcessPath = [string]$process.Path } catch { $actualProcessPath = "" }
        }
        $samePath = -not [string]::IsNullOrWhiteSpace($actualProcessPath) -and $actualProcessPath -ieq $recordedProcessPath

        $recordedStart = [DateTime]::Parse(
            [string]$entry.started_at_utc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
        $actualStart = $null
        try { $actualStart = $process.StartTime } catch { $actualStart = $null }
        if ($null -eq $actualStart -and $null -ne $processInfo.CreationDate) {
            try { $actualStart = [DateTime]$processInfo.CreationDate } catch { $actualStart = $null }
        }
        if ($null -eq $actualStart) {
            if ($null -eq (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
                $alreadyExited += [string]$entry.service
            } else {
                $skipped += [string]$entry.service
            }
            continue
        }
        $sameStartTime = [Math]::Abs(($actualStart.ToUniversalTime() - $recordedStart.ToUniversalTime()).TotalSeconds) -le 2

        $processName = [IO.Path]::GetFileNameWithoutExtension([string]$processInfo.Name)
        $isPowerShell = $processName -in @("powershell", "pwsh")
        $sameScript = $true
        if (-not [string]::IsNullOrWhiteSpace([string]$entry.script_path)) {
            $sameScript = [string]$processInfo.CommandLine -match [regex]::Escape([string]$entry.script_path)
        }
        if (-not $samePath -or -not $sameStartTime -or -not $isPowerShell -or -not $sameScript) {
            $skipped += [string]$entry.service
            continue
        }

        if (Stop-ProcessTreeIfPresent -ProcessId $pidValue) { $stopped += [string]$entry.service }
        else { $skipped += [string]$entry.service }
    }

    Remove-Item -LiteralPath $statePath -Force
} else {
    Write-Host "No launcher-owned Veyra processes are recorded." -ForegroundColor Yellow
}

# A Next.js child can outlive the PowerShell launcher recorded in state.json.
# Kill only Node/PowerShell processes whose command line contains this exact
# repository frontend path or start-frontend.ps1, so unrelated port-3000 apps
# are untouched.
$frontendProcesses = @(Get-VeyraFrontendProcesses)
foreach ($frontend in $frontendProcesses) {
    $pidValue = [int]$frontend.ProcessId
    if (Stop-ProcessTreeIfPresent -ProcessId $pidValue) {
        $stopped += "Frontend child"
    } else {
        $skipped += "Frontend child PID $pidValue"
    }
}

# The execution controller has no listening port and can outlive its launcher if
# a previous shell was interrupted. Kill only exact controllers from this
# project's virtualenv and management command so unrelated Python is untouched.
$controllers = @(Get-ExecutionControllers)
foreach ($controller in $controllers) {
    $pidValue = [int]$controller.ProcessId
    if (Stop-ProcessTreeIfPresent -ProcessId $pidValue) {
        $stopped += "Execution layer controller"
    } else {
        $skipped += "Execution layer controller PID $pidValue"
    }
}

Write-Host "Veyra local shutdown summary" -ForegroundColor Cyan
Write-Host "----------------------------" -ForegroundColor Cyan
if ($stopped.Count -gt 0) { Write-Host "STOPPED: $($stopped -join ', ')" -ForegroundColor Green }
if ($alreadyExited.Count -gt 0) { Write-Host "ALREADY EXITED: $($alreadyExited -join ', ')" -ForegroundColor Yellow }
if ($skipped.Count -gt 0) { Write-Host "SKIPPED (ownership could not be verified): $($skipped -join ', ')" -ForegroundColor Red }
if ($stopped.Count -eq 0 -and $alreadyExited.Count -eq 0 -and $skipped.Count -eq 0) { Write-Host "No launcher-owned Veyra processes were running." -ForegroundColor Yellow }
Write-Host "PostgreSQL was not stopped." -ForegroundColor Cyan