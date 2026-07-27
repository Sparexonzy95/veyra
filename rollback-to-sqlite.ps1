$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\cashkink\Downloads\Veyra-backend"
$backendRoot = Join-Path $projectRoot "veyra-client-backend"
$backupBase = Join-Path $projectRoot "_database_backups"
$backendEnv = Join-Path $backendRoot ".env"
$sqliteDb = Join-Path $backendRoot "db.sqlite3"

$ports = @(3000, 8000, 9100, 9200)
if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    $busy = @()
    foreach ($port in $ports) {
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
            $busy += $port
        }
    }
    if ($busy.Count -gt 0) {
        throw "Stop every Veyra server first. Listening ports: $($busy -join ', ')"
    }
}

$latest = Get-ChildItem -LiteralPath $backupBase -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "native-postgres-*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $latest) {
    throw "No native PostgreSQL migration backup was found."
}

$backupDb = Join-Path $latest.FullName "db.sqlite3"
$backupEnv = Join-Path $latest.FullName ".env.before-postgres"

if (-not (Test-Path -LiteralPath $backupDb)) {
    throw "SQLite backup is missing: $backupDb"
}

Copy-Item -LiteralPath $backupDb -Destination $sqliteDb -Force

if (Test-Path -LiteralPath $backupEnv) {
    Copy-Item -LiteralPath $backupEnv -Destination $backendEnv -Force
}
elseif (Test-Path -LiteralPath $backendEnv) {
    $output = @(Get-Content -LiteralPath $backendEnv | Where-Object { $_ -notmatch "^\s*DATABASE_URL\s*=" })
    [IO.File]::WriteAllLines(
        $backendEnv,
        [string[]]$output,
        [Text.UTF8Encoding]::new($false)
    )
}

Write-Host "SQLite restored from: $($latest.FullName)" -ForegroundColor Green
Write-Host "The PostgreSQL database was not deleted." -ForegroundColor Yellow
