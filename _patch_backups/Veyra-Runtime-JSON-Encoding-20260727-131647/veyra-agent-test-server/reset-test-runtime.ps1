param(
    [switch]$FullIdentityReset
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$stateDir = Join-Path $root ".veyra-runtime"
$statePath = Join-Path $stateDir "state.json"

if (-not (Test-Path -LiteralPath $stateDir)) {
    Write-Host "No local runtime state exists." -ForegroundColor Yellow
    exit 0
}

if ($FullIdentityReset) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupDir = Join-Path $root "_runtime_identity_backups\$stamp"
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    Copy-Item -LiteralPath $stateDir -Destination $backupDir -Recurse -Force
    Remove-Item -LiteralPath $stateDir -Recurse -Force
    Write-Host "Full runtime identity reset completed." -ForegroundColor Yellow
    Write-Host "Backup: $backupDir" -ForegroundColor Yellow
    Write-Host "A new Veyra connection link will be required." -ForegroundColor Yellow
    exit 0
}

if (-not (Test-Path -LiteralPath $statePath)) {
    throw "Runtime state file was not found: $statePath"
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json

function Set-StateValue {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )
    $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
}

# Clear only transient work state. Never erase runtime identity, signing key,
# Veyra credential, agent binding, or heartbeat URLs during a job retry.
Set-StateValue $state "qualification_id" ""
Set-StateValue $state "qualification_status" "waiting"
Set-StateValue $state "qualification_message" "Waiting for Veyra"
Set-StateValue $state "qualification_updated_at" ""
Set-StateValue $state "job_assignment_id" ""
Set-StateValue $state "job_lease_id" ""
Set-StateValue $state "job_assignment_attempt" 0
Set-StateValue $state "job_onchain_id" ""
Set-StateValue $state "job_status" "waiting"
Set-StateValue $state "job_message" "Waiting for paid work"
Set-StateValue $state "job_updated_at" ""
Set-StateValue $state "verification_assignment_id" ""
Set-StateValue $state "verification_status" "waiting"
Set-StateValue $state "verification_message" "Waiting for a submitted worker job"
Set-StateValue $state "verification_updated_at" ""

$state | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $statePath -Encoding UTF8

foreach ($name in @("jobs", "qualification", "verification")) {
    $path = Join-Path $stateDir $name
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

Write-Host "Transient runtime work state reset." -ForegroundColor Green
Write-Host "Veyra identity and connection credential were preserved." -ForegroundColor Green
