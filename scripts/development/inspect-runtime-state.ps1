$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$root = Join-Path $projectRoot "agent-starter"
$canonical = Join-Path $root ".veyra-runtime\state.json"

Write-Host "=== PORT 9100 ===" -ForegroundColor Cyan
$listener = Get-NetTCPConnection -LocalPort 9100 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    [pscustomobject]@{
        PID = $listener.OwningProcess
        Executable = $process.ExecutablePath
        CommandLine = $process.CommandLine
    } | Format-List
} else {
    Write-Host "No process is listening on port 9100."
}

Write-Host "=== CANONICAL STATE ===" -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $canonical)) {
    Write-Host "Missing: $canonical" -ForegroundColor Red
} else {
    $state = Get-Content -LiteralPath $canonical -Raw | ConvertFrom-Json
    [pscustomobject]@{
        Path = $canonical
        RuntimeId = $state.runtime_id
        AgentId = $state.agent_id
        AgentName = $state.agent_name
        CredentialPresent = -not [string]::IsNullOrWhiteSpace([string]$state.runtime_credential)
        HeartbeatUrl = $state.heartbeat_url
    } | Format-List
}

Write-Host "=== ALL LOCAL STATE FILES ===" -ForegroundColor Cyan
Get-ChildItem $projectRoot -Recurse -Force -File -Filter "state.json" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $state = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
        [pscustomobject]@{
            Path = $_.FullName
            RuntimeId = $state.runtime_id
            AgentId = $state.agent_id
            CredentialPresent = -not [string]::IsNullOrWhiteSpace([string]$state.runtime_credential)
        }
    } catch {}
} | Format-Table -AutoSize
