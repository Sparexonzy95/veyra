param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$OutputDirectory = (Join-Path ([IO.Path]::GetTempPath()) "veyra-snapshots")
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$stage = Join-Path $env:TEMP "Veyra-Safe-Source-$stamp"
$zipPath = Join-Path $OutputDirectory "Veyra-Safe-Source-$stamp.zip"
$hashPath = "$zipPath.sha256.txt"

$excludedDirectoryNames = @(
    ".git", ".venv", "venv", "node_modules", ".next", "__pycache__",
    ".pytest_cache", ".veyra-runtime", "_database_backups",
    "_runtime_identity_backups", "_patch_backups", "_safe_source_backups",
    "staticfiles", "media"
)
$excludedFilePatterns = @(
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
    "db.sqlite3", "*.sqlite", "*.sqlite3", "*.log", "*.zip",
    "*.sha256.txt", "*.pyc"
)

function Copy-SafeSourceTree {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDirectory,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$RelativeDirectory,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )

    Get-ChildItem -LiteralPath $SourceDirectory -Force | ForEach-Object {
        $relative = if ($RelativeDirectory) {
            Join-Path $RelativeDirectory $_.Name
        }
        else {
            $_.Name
        }

        if ($_.PSIsContainer) {
            if ($excludedDirectoryNames -contains $_.Name) {
                return
            }
            Copy-SafeSourceTree `
                -SourceDirectory $_.FullName `
                -RelativeDirectory $relative `
                -DestinationRoot $DestinationRoot
            return
        }

        foreach ($pattern in $excludedFilePatterns) {
            if ($_.Name -like $pattern) {
                return
            }
        }
        $destination = Join-Path $DestinationRoot $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }
}

try {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
    New-Item -ItemType Directory -Path $stage -Force | Out-Null

    Copy-SafeSourceTree `
        -SourceDirectory $ProjectRoot `
        -RelativeDirectory "" `
        -DestinationRoot $stage

    $forbidden = Get-ChildItem -LiteralPath $stage -Recurse -Force -File | Where-Object {
        $_.Name -eq ".env" -or
        $_.Name -like ".env.*" -or
        $_.Extension -in @(".pem", ".key", ".p12", ".pfx") -or
        $_.FullName -match "[\\/]\.veyra-runtime[\\/]"
    }
    if ($forbidden) {
        throw "Snapshot safety check failed: forbidden runtime or secret files remain."
    }

    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath -Force
    $hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $(Split-Path -Leaf $zipPath)" | Set-Content -LiteralPath $hashPath -Encoding ASCII

    Write-Host "Safe source snapshot created." -ForegroundColor Green
    Write-Host "Archive: $zipPath" -ForegroundColor Green
    Write-Host "SHA-256: $hash" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}
