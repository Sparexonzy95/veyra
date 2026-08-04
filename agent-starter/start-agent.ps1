$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$envFile = Join-Path $root ".env"
$stateDir = Join-Path $root ".veyra-runtime"
$statePath = Join-Path $stateDir "state.json"

if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Write-Host "Created .env. Add the owner-paid AI_API_KEY, then run this script again." -ForegroundColor Yellow
    notepad $envFile
    exit 1
}

$runtimePort = [Environment]::GetEnvironmentVariable("RUNTIME_PORT", "Process")
if ([string]::IsNullOrWhiteSpace($runtimePort)) {
    $portSetting = Get-Content -LiteralPath $envFile |
        Where-Object { $_ -match "^\s*RUNTIME_PORT\s*=" } |
        Select-Object -Last 1
    if ($portSetting -match "^\s*RUNTIME_PORT\s*=\s*(\d+)\s*(?:#.*)?$") {
        $runtimePort = $Matches[1]
    }
}

if ([string]::IsNullOrWhiteSpace($runtimePort)) {
    $runtimePort = "9100"
}

$parsedPort = 0
if (-not [int]::TryParse($runtimePort, [ref]$parsedPort) -or $parsedPort -lt 1 -or $parsedPort -gt 65535) {
    throw "RUNTIME_PORT must be an integer from 1 through 65535."
}

# Refuse to hide another runtime behind this starter's configured port.
$listener = Get-NetTCPConnection -LocalPort $parsedPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $command = if ($process) { $process.CommandLine } else { "Unknown command" }
    throw "Port $parsedPort is already in use by PID $($listener.OwningProcess): $command`nStop that process before starting this Veyra Agent Starter."
}

# Pin the runtime to this exact project directory. These process-level values
# take precedence over any stale path values inside .env or the parent shell.
$env:VEYRA_RUNTIME_ENV_FILE = $envFile
$env:VEYRA_RUNTIME_STATE_DIR = $stateDir

if (Test-Path -LiteralPath $statePath) {
    Write-Host "Reusing the existing Veyra runtime identity." -ForegroundColor Cyan
}
else {
    Write-Host "No runtime identity exists yet. Creating a new private identity for this starter." -ForegroundColor Cyan
}
Write-Host "State directory: $stateDir" -ForegroundColor Cyan
Write-Host "Listening port: $parsedPort" -ForegroundColor Cyan

$projectRoot = Split-Path -Parent $root
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

& $python (Join-Path $root "server.py")
