param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot = "C:\Users\cashkink\Downloads\Veyra-backend"
)

$ErrorActionPreference = "Stop"
$PatchRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackupRoot = "C:\Users\cashkink\Downloads\Veyra-AgentOwner-Phase1-Step2-Backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

function Install-PatchTree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [bool]$RequireExisting
    )

    if (-not (Test-Path $SourceRoot)) {
        return
    }

    Get-ChildItem -Path $SourceRoot -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($SourceRoot.Length).TrimStart('\', '/')
        $target = Join-Path $ProjectRoot $relative
        $backup = Join-Path $BackupRoot $relative

        if ($RequireExisting -and -not (Test-Path -LiteralPath $target)) {
            throw "Required replacement target is missing: $target"
        }

        if (Test-Path -LiteralPath $target) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
            Copy-Item -LiteralPath $target -Destination $backup -Force
        }

        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        Write-Host "[INSTALLED] $relative"
    }
}

if (-not (Test-Path $ProjectRoot)) {
    throw "Project root does not exist: $ProjectRoot"
}

Install-PatchTree -SourceRoot (Join-Path $PatchRoot "CHANGED_FILES") -RequireExisting $true
Install-PatchTree -SourceRoot (Join-Path $PatchRoot "NEW_FILES") -RequireExisting $false

Write-Host ""
Write-Host "Runtime pairing patch installed."
Write-Host "Backup: $BackupRoot"
Write-Host "No migration, Circle operation, GitHub operation, or Arc transaction was run."
