param(
    [string]$ExpectedAgentId = "85e13516-0339-4355-aaec-ca4d6794c4bd"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$statePath = Join-Path $root ".veyra-runtime\state.json"
$backupPath = "$statePath.before-ai402-retry"
$keyPath = Join-Path $root ".veyra-runtime\ed25519-private.pem"

if (-not (Test-Path -LiteralPath $statePath)) {
    throw "Current runtime state was not found: $statePath"
}
if (-not (Test-Path -LiteralPath $backupPath)) {
    throw "The pre-402 runtime backup was not found: $backupPath"
}
if (-not (Test-Path -LiteralPath $keyPath)) {
    throw "The runtime signing key was not found: $keyPath"
}

$current = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$backup = Get-Content -LiteralPath $backupPath -Raw | ConvertFrom-Json

function Set-StateValue {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )
    $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
}

if ([string]::IsNullOrWhiteSpace([string]$backup.runtime_credential)) {
    throw "The backup has no Veyra runtime credential."
}
if ([string]$backup.agent_id -ne $ExpectedAgentId) {
    throw "The backup belongs to a different agent. Expected $ExpectedAgentId."
}

$connectionFields = @(
    "runtime_id",
    "one_time_token",
    "token_expires_at",
    "token_consumed",
    "agent_id",
    "agent_name",
    "runtime_credential",
    "heartbeat_url",
    "configuration_url",
    "agent_configuration",
    "connected_at"
)

foreach ($field in $connectionFields) {
    Set-StateValue $current $field $backup.$field
}

Set-StateValue $current "last_heartbeat_at" ""
Set-StateValue $current "last_heartbeat_error" "Connection restored; restart LogicBloom to authenticate."
Set-StateValue $current "qualification_id" ""
Set-StateValue $current "qualification_status" "waiting"
Set-StateValue $current "qualification_message" "Waiting for Veyra"
Set-StateValue $current "qualification_updated_at" ""
Set-StateValue $current "job_assignment_id" ""
Set-StateValue $current "job_lease_id" ""
Set-StateValue $current "job_assignment_attempt" 0
Set-StateValue $current "job_onchain_id" ""
Set-StateValue $current "job_status" "waiting"
Set-StateValue $current "job_message" "Waiting for paid work"
Set-StateValue $current "job_updated_at" ""
Set-StateValue $current "verification_assignment_id" ""
Set-StateValue $current "verification_status" "waiting"
Set-StateValue $current "verification_message" "Waiting for a submitted worker job"
Set-StateValue $current "verification_updated_at" ""

$current | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $statePath -Encoding UTF8

$verified = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace([string]$verified.runtime_credential)) {
    throw "Restore verification failed: runtime credential is still missing."
}
if ([string]$verified.agent_id -ne $ExpectedAgentId) {
    throw "Restore verification failed: agent ID does not match LogicBloom."
}

Write-Host "LogicBloom Veyra connection restored from the pre-402 backup." -ForegroundColor Green
Write-Host "State file: $statePath" -ForegroundColor Cyan
Write-Host "Runtime ID: $($verified.runtime_id)" -ForegroundColor Cyan
Write-Host "Agent ID: $($verified.agent_id)" -ForegroundColor Cyan
Write-Host "Credential present: True" -ForegroundColor Cyan
Write-Host "The AI provider key in .env was not read or changed." -ForegroundColor Green
Write-Host "Restart LogicBloom, then check /veyra/health." -ForegroundColor Cyan
