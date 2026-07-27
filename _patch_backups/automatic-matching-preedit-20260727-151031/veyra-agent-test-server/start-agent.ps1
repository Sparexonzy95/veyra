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

if (-not (Test-Path -LiteralPath $statePath)) {
    throw "LogicBloom state file is missing: $statePath"
}

# Refuse to hide an older runtime behind the same port.
$listener = Get-NetTCPConnection -LocalPort 9100 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $command = if ($process) { $process.CommandLine } else { "Unknown command" }
    throw "Port 9100 is already in use by PID $($listener.OwningProcess): $command`nStop that process before starting LogicBloom."
}

# Pin the runtime to this exact project directory. These process-level values
# take precedence over any stale path values inside .env or the parent shell.
$env:VEYRA_RUNTIME_ENV_FILE = $envFile
$env:VEYRA_RUNTIME_STATE_DIR = $stateDir

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$paired = -not [string]::IsNullOrWhiteSpace([string]$state.runtime_credential)

Write-Host "LogicBloom state file: $statePath" -ForegroundColor Cyan
Write-Host "Runtime ID: $($state.runtime_id)" -ForegroundColor Cyan
Write-Host "Agent ID: $($state.agent_id)" -ForegroundColor Cyan
Write-Host "Paired credential present: $paired" -ForegroundColor Cyan

if (-not $paired) {
    throw "The canonical LogicBloom state is not paired. Run .\restore-agent-connection.ps1 first."
}

$python = "C:\Users\cashkink\Downloads\Veyra-backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

& $python (Join-Path $root "server.py")
