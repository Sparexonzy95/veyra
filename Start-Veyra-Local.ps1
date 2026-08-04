param(
    [ValidateRange(1, 180)]
    [int]$FrontendWaitSeconds = 90,
    [ValidateRange(1, 180)]
    [int]$AgentWaitSeconds = 60
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$projectRoot = $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".veyra-local"
$statePath = Join-Path $runtimeRoot "state.json"
$postgresServiceName = "postgresql-x64-17"
$powershellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$identitySource = "C:\Users\cashkink\Downloads\Veyra-Agent-Starter-Test-2\.veyra-runtime"

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

function Get-ConfiguredAgentPort {
    $envPath = Join-Path $projectRoot "agent-starter\.env"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        return $null
    }

    $setting = Get-Content -LiteralPath $envPath |
        Where-Object { $_ -match "^\s*RUNTIME_PORT\s*=" } |
        Select-Object -Last 1
    if ($setting -match "^\s*RUNTIME_PORT\s*=\s*[`"']?(\d+)[`"']?\s*(?:#.*)?$") {
        $candidate = [int]$Matches[1]
        if ($candidate -ge 1 -and $candidate -le 65535) {
            return $candidate
        }
    }
    return $null
}

function Get-PortOwner {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
}

function Test-HttpReachable {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 3 -ErrorAction Stop | Out-Null
        return $true
    }
    catch {
        # Redirects and HTTP error responses still prove that an HTTP server answered.
        if ($null -ne $_.Exception.Response) { return $true }
        return $false
    }
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

function Get-ExecutionControllers {
    $pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
    return @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -match "manage\.py\s+run_execution_layer" -and
            $_.ExecutablePath -eq $pythonPath
        })
}

function Test-PythonRuntime {
    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { return $false }
    & $python -c "import django" 2>$null
    return $LASTEXITCODE -eq 0
}

function Get-OwnedProcesses {
    $owned = @()
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { return $owned }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $owned = @($state.processes)
    }
    catch {
        Write-Warning "Ignoring an unreadable local launcher state file. No unverified process will be adopted."
    }
    return $owned
}

function Save-OwnedProcesses {
    param([AllowEmptyCollection()][object[]]$Processes)

    if (@($Processes).Count -eq 0) {
        if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath -Force }
        return
    }
    $payload = [ordered]@{ version = 2; processes = @($Processes) } | ConvertTo-Json -Depth 5
    [IO.File]::WriteAllText($statePath, $payload, [Text.UTF8Encoding]::new($false))
}

function Start-LauncherProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [switch]$CaptureOutput
    )

    $arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    $startArguments = @{
        FilePath = $powershellPath
        ArgumentList = $arguments
        WorkingDirectory = $projectRoot
        PassThru = $true
    }
    $stdoutName = ""
    $stderrName = ""
    if ($CaptureOutput) {
        $safeName = $Service.ToLowerInvariant() -replace "[^a-z0-9]+", "-"
        $stdoutName = "$safeName.stdout.log"
        $stderrName = "$safeName.stderr.log"
        $stdoutPath = Join-Path $runtimeRoot $stdoutName
        $stderrPath = Join-Path $runtimeRoot $stderrName
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
        $startArguments.RedirectStandardOutput = $stdoutPath
        $startArguments.RedirectStandardError = $stderrPath
    }
    $process = Start-Process @startArguments
    $process.Refresh()
    $processPath = [string]$process.Path
    if ([string]::IsNullOrWhiteSpace($processPath)) { $processPath = $powershellPath }
    return [pscustomobject]@{
        service = $Service
        pid = $process.Id
        process_path = $processPath
        started_at_utc = $process.StartTime.ToUniversalTime().ToString("o")
        script_path = [IO.Path]::GetFullPath($ScriptPath)
        stdout_log = $stdoutName
        stderr_log = $stderrName
    }
}

function Get-SafeFailureLines {
    param([Parameter(Mandatory = $true)][object]$Entry)

    $lines = @()
    foreach ($property in @("stderr_log", "stdout_log")) {
        $name = [string]$Entry.$property
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        $path = Join-Path $runtimeRoot $name
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $lines += Get-Content -LiteralPath $path -Tail 30 -ErrorAction SilentlyContinue
        }
    }
    $nonSecret = @($lines | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_) -and
        $_ -notmatch "(?i)token|secret|api[_-]?key|private[_-]?key|credential|connection[_-]?link|authorization|\.env" -and
        $_ -notmatch "^\s*[A-Za-z_][A-Za-z0-9_]*\s*=" -and
        $_ -notmatch "(?i)-----BEGIN|bearer\s+|[?&](?:token|key|secret)="
    })
    $safe = @($nonSecret | Where-Object {
        $_ -match "(?i)error|err!|failed|exception|cannot|unable|missing|not found|in use|lock|exited|elifecycle|eaddrinuse|enoent|module_not_found|syntaxerror|typeerror"
    } | Select-Object -Last 5)
    if ($safe.Count -eq 0) { $safe = @($nonSecret | Select-Object -Last 5) }
    if ($safe.Count -eq 0) { return "Process exited before becoming ready; see the ignored .veyra-local log files." }
    return ($safe -join " | ")
}

function Wait-ForHttpService {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [object]$Entry
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (Test-HttpReachable $Url) { return [pscustomobject]@{ Ready = $true; Detail = "HTTP endpoint is reachable." } }
        if ($null -ne $Entry -and $null -eq (Get-Process -Id ([int]$Entry.pid) -ErrorAction SilentlyContinue)) {
            return [pscustomobject]@{ Ready = $false; Detail = Get-SafeFailureLines $Entry }
        }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    return [pscustomobject]@{ Ready = $false; Detail = "Timed out after $TimeoutSeconds seconds waiting for $Url." }
}

function New-Result {
    param([string]$Service, [string]$Status, [string]$Endpoint, [string]$Detail)
    return [pscustomobject]@{ Service = $Service; Status = $Status; Endpoint = $Endpoint; Detail = $Detail }
}

function Add-OwnedEntry {
    param([object]$Entry)
    $script:ownedProcesses = @($script:ownedProcesses) + @($Entry)
    Save-OwnedProcesses -Processes $script:ownedProcesses
}

$results = [ordered]@{}
$ownedProcesses = @(Get-OwnedProcesses)
$pythonReady = Test-PythonRuntime
$agentPort = Get-ConfiguredAgentPort

Write-Host "Starting the local Veyra stack..." -ForegroundColor Cyan

$postgres = Get-Service -Name $postgresServiceName -ErrorAction SilentlyContinue
if ($null -eq $postgres) {
    $results.PostgreSQL = New-Result "PostgreSQL" "FAILED" "localhost:5432" "Windows service $postgresServiceName was not found."
}
else {
    try {
        if ($postgres.Status -ne "Running") {
            Start-Service -Name $postgresServiceName
            $postgres.WaitForStatus("Running", [TimeSpan]::FromSeconds(20))
            $status = "RUNNING"
        } else { $status = "ALREADY RUNNING" }
        if ($null -eq (Get-PortOwner 5432)) { throw "Port 5432 is not listening." }
        $results.PostgreSQL = New-Result "PostgreSQL" $status "localhost:5432" "Windows service and port 5432 are reachable."
    }
    catch { $results.PostgreSQL = New-Result "PostgreSQL" "FAILED" "localhost:5432" $_.Exception.Message }
}

$backendUrl = "http://localhost:8000/api/health/"
$backendOwner = Get-PortOwner 8000
if ($null -ne $backendOwner) {
    if (Test-HttpReachable $backendUrl) { $results.Backend = New-Result "Backend" "ALREADY RUNNING" $backendUrl "Existing HTTP service is reachable." }
    else { $results.Backend = New-Result "Backend" "FAILED" $backendUrl "Port 8000 is occupied but the backend health endpoint is not reachable." }
}
elseif (-not $pythonReady) { $results.Backend = New-Result "Backend" "FAILED" $backendUrl "Python environment or Django dependency is missing." }
else {
    $entry = Start-LauncherProcess "Backend" (Join-Path $projectRoot "start-backend.ps1")
    Add-OwnedEntry $entry
    $check = Wait-ForHttpService $backendUrl 60 $entry
    $results.Backend = New-Result "Backend" $(if ($check.Ready) { "RUNNING" } else { "FAILED" }) $backendUrl $check.Detail
}

$frontendUrl = "http://localhost:3000"
$frontendOwner = Get-PortOwner 3000
$frontendProcesses = @(Get-VeyraFrontendProcesses)
if ($null -ne $frontendOwner) {
    if (Test-VeyraFrontendProcess $frontendOwner) {
        $check = Wait-ForHttpService $frontendUrl $FrontendWaitSeconds $null
        if ($check.Ready) {
            $results.Frontend = New-Result "Frontend" "ALREADY RUNNING" $frontendUrl "Existing Veyra frontend is reachable; no duplicate was started."
        } else {
            $results.Frontend = New-Result "Frontend" "FAILED" $frontendUrl "A Veyra frontend process owns port 3000, but it did not become HTTP-ready within $FrontendWaitSeconds seconds."
        }
    } else { $results.Frontend = New-Result "Frontend" "FAILED" $frontendUrl "Port 3000 is occupied by a service that could not be verified as the Veyra frontend." }
}
elseif ($frontendProcesses.Count -gt 0) {
    $check = Wait-ForHttpService $frontendUrl $FrontendWaitSeconds $null
    if ($check.Ready) {
        $results.Frontend = New-Result "Frontend" "ALREADY RUNNING" $frontendUrl "Existing Veyra frontend finished starting; no duplicate was started."
    } else {
        $results.Frontend = New-Result "Frontend" "FAILED" $frontendUrl "A Veyra frontend process was already starting, but it did not become HTTP-ready within $FrontendWaitSeconds seconds."
    }
}
elseif (-not (Test-Path -LiteralPath (Join-Path $projectRoot "frontend\node_modules") -PathType Container)) {
    $results.Frontend = New-Result "Frontend" "FAILED" $frontendUrl "frontend/node_modules is missing; dependencies were not reinstalled."
}
elseif ($null -eq (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    $results.Frontend = New-Result "Frontend" "FAILED" $frontendUrl "npm.cmd was not found."
}
else {
    foreach ($nextLock in @(
        (Join-Path $projectRoot "frontend\.next\dev\lock"),
        (Join-Path $projectRoot "frontend\.next\lock")
    )) {
        if (Test-Path -LiteralPath $nextLock -PathType Leaf) {
            Remove-Item -LiteralPath $nextLock -Force
        }
    }
    $entry = Start-LauncherProcess "Frontend" (Join-Path $projectRoot "start-frontend.ps1") -CaptureOutput
    Add-OwnedEntry $entry
    $check = Wait-ForHttpService $frontendUrl $FrontendWaitSeconds $entry
    $results.Frontend = New-Result "Frontend" $(if ($check.Ready) { "RUNNING" } else { "FAILED" }) $frontendUrl $check.Detail
}

$agentUrl = if ($null -ne $agentPort) { "http://127.0.0.1:$agentPort/veyra/health" } else { "unavailable" }
if ($null -eq $agentPort) {
    $results.AgentStarter = New-Result "Demo Agent Starter" "FAILED" $agentUrl "RUNTIME_PORT is missing or invalid in agent-starter/.env."
}
else {
    Write-Host "Agent Starter configured port: $agentPort" -ForegroundColor Cyan
    $agentOwner = Get-PortOwner $agentPort
    if ($null -ne $agentOwner) {
        if (Test-HttpReachable $agentUrl) { $results.AgentStarter = New-Result "Demo Agent Starter" "ALREADY RUNNING" $agentUrl "Existing configured health endpoint is reachable." }
        else { $results.AgentStarter = New-Result "Demo Agent Starter" "FAILED" $agentUrl "Configured port is occupied but the health endpoint is not reachable." }
    }
    else {
        $destinationIdentity = Join-Path $projectRoot "agent-starter\.veyra-runtime"
        if (-not (Test-Path -LiteralPath $destinationIdentity -PathType Container)) {
            if (Test-Path -LiteralPath $identitySource -PathType Container) {
                Copy-Item -LiteralPath $identitySource -Destination $destinationIdentity -Recurse -ErrorAction Stop
                Write-Host "Restored the existing Agent Starter identity directory without reading or replacing its files." -ForegroundColor Cyan
            }
        }
        if (-not (Test-Path -LiteralPath $destinationIdentity -PathType Container)) {
            $results.AgentStarter = New-Result "Demo Agent Starter" "FAILED" $agentUrl "No existing Agent Starter identity was found; no identity was generated."
        }
        elseif (-not $pythonReady) { $results.AgentStarter = New-Result "Demo Agent Starter" "FAILED" $agentUrl "Python environment or runtime dependencies are missing." }
        else {
            $entry = Start-LauncherProcess "Demo Agent Starter" (Join-Path $projectRoot "agent-starter\start-agent.ps1")
            Add-OwnedEntry $entry
            $check = Wait-ForHttpService $agentUrl $AgentWaitSeconds $entry
            $results.AgentStarter = New-Result "Demo Agent Starter" $(if ($check.Ready) { "RUNNING" } else { "FAILED" }) $agentUrl $check.Detail
        }
    }
}

$verifierUrl = "http://127.0.0.1:9200/veyra/health"
$verifierOwner = Get-PortOwner 9200
if ($null -ne $verifierOwner) {
    if (Test-HttpReachable $verifierUrl) { $results.Verifier = New-Result "Verifier" "ALREADY RUNNING" $verifierUrl "Existing health endpoint is reachable." }
    else { $results.Verifier = New-Result "Verifier" "FAILED" $verifierUrl "Port 9200 is occupied but the verifier health endpoint is not reachable." }
}
elseif (-not $pythonReady) { $results.Verifier = New-Result "Verifier" "FAILED" $verifierUrl "Python environment or runtime dependencies are missing." }
else {
    $entry = Start-LauncherProcess "Verifier" (Join-Path $projectRoot "start-verifier.ps1")
    Add-OwnedEntry $entry
    $check = Wait-ForHttpService $verifierUrl 60 $entry
    $results.Verifier = New-Result "Verifier" $(if ($check.Ready) { "RUNNING" } else { "FAILED" }) $verifierUrl $check.Detail
}

$controllers = @(Get-ExecutionControllers)
if ($controllers.Count -eq 1) {
    $results.ExecutionLayer = New-Result "Execution layer" "ALREADY RUNNING" "process: run_execution_layer" "Exactly one controller process is active."
}
elseif ($controllers.Count -gt 1) {
    $results.ExecutionLayer = New-Result "Execution layer" "FAILED" "process: run_execution_layer" "Multiple execution-layer controllers are already active; none was started or stopped."
}
elseif (-not $pythonReady) { $results.ExecutionLayer = New-Result "Execution layer" "FAILED" "process: run_execution_layer" "Python environment or Django dependency is missing." }
else {
    $entry = Start-LauncherProcess "Execution layer" (Join-Path $projectRoot "start-execution-layer.ps1")
    Add-OwnedEntry $entry
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        Start-Sleep -Seconds 1
        $controllers = @(Get-ExecutionControllers)
    } while ($controllers.Count -eq 0 -and [DateTime]::UtcNow -lt $deadline -and $null -ne (Get-Process -Id $entry.pid -ErrorAction SilentlyContinue))
    if ($controllers.Count -eq 1) { $results.ExecutionLayer = New-Result "Execution layer" "RUNNING" "process: run_execution_layer" "Exactly one controller process is active." }
    elseif ($controllers.Count -gt 1) { $results.ExecutionLayer = New-Result "Execution layer" "FAILED" "process: run_execution_layer" "Multiple execution-layer controllers were detected." }
    else { $results.ExecutionLayer = New-Result "Execution layer" "FAILED" "process: run_execution_layer" (Get-SafeFailureLines $entry) }
}

$ownedProcesses = @(Get-OwnedProcesses)
Save-OwnedProcesses -Processes $ownedProcesses

Write-Host ""
Write-Host "Veyra local stack summary" -ForegroundColor Cyan
Write-Host "-------------------------" -ForegroundColor Cyan
foreach ($result in $results.Values) {
    $color = switch ($result.Status) { "RUNNING" { "Green" }; "ALREADY RUNNING" { "Yellow" }; default { "Red" } }
    Write-Host ("{0,-20} {1,-16} {2}" -f $result.Service, $result.Status, $result.Endpoint) -ForegroundColor $color
    Write-Host ("  {0}" -f $result.Detail) -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "Stop only launcher-owned Veyra processes with .\Stop-Veyra-Local.ps1" -ForegroundColor Cyan

if (@($results.Values | Where-Object { $_.Status -eq "FAILED" }).Count -gt 0) { exit 1 }