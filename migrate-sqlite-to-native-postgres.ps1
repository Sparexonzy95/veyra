$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\cashkink\Downloads\Veyra-backend"
$backendRoot = Join-Path $projectRoot "veyra-client-backend"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backendEnv = Join-Path $backendRoot ".env"
$sqliteDb = Join-Path $backendRoot "db.sqlite3"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Join-Path $projectRoot "_database_backups\native-postgres-$timestamp"
$dumpFile = Join-Path $backupRoot "veyra-sqlite-data.json"

$databaseName = "veyra"
$databaseUser = "veyra_app"
$databaseHost = "127.0.0.1"
$databasePort = "5432"

function ConvertFrom-SecureValue {
    param([Security.SecureString]$SecureValue)

    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        $lines = @(Get-Content -LiteralPath $Path)
    }

    $pattern = "^\s*" + [regex]::Escape($Name) + "\s*="
    $written = $false
    $output = foreach ($line in $lines) {
        if ($line -match $pattern) {
            if (-not $written) {
                "$Name=$Value"
                $written = $true
            }
        }
        else {
            $line
        }
    }

    if (-not $written) {
        $output += "$Name=$Value"
    }

    [IO.File]::WriteAllLines(
        $Path,
        [string[]]$output,
        [Text.UTF8Encoding]::new($false)
    )
}

function Remove-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $pattern = "^\s*" + [regex]::Escape($Name) + "\s*="
    $output = @(Get-Content -LiteralPath $Path | Where-Object { $_ -notmatch $pattern })

    [IO.File]::WriteAllLines(
        $Path,
        [string[]]$output,
        [Text.UTF8Encoding]::new($false)
    )
}

function Find-PostgresBinary {
    param([Parameter(Mandatory = $true)][string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        "C:\Program Files\PostgreSQL\18\bin\$Name.exe",
        "C:\Program Files\PostgreSQL\17\bin\$Name.exe",
        "C:\Program Files\PostgreSQL\16\bin\$Name.exe",
        "C:\Program Files\PostgreSQL\15\bin\$Name.exe",
        "C:\Program Files\PostgreSQL\14\bin\$Name.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw @"
PostgreSQL command '$Name' was not found.

Install PostgreSQL for Windows first. During installation:
- keep port 5432
- remember the password you set for the postgres administrator
- Stack Builder is optional and can be skipped

Then run this migration script again.
"@
}

Write-Host "Veyra SQLite -> Native PostgreSQL migration" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path -LiteralPath $backendRoot)) {
    throw "Backend folder not found: $backendRoot"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Veyra Python environment not found: $python"
}
if (-not (Test-Path -LiteralPath $sqliteDb)) {
    throw "SQLite database not found: $sqliteDb"
}

$ports = @(3000, 8000, 9100, 9200)
if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    $busy = @()
    foreach ($port in $ports) {
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
            $busy += $port
        }
    }
    if ($busy.Count -gt 0) {
        throw "Stop all Veyra servers first with Ctrl+C. Listening ports: $($busy -join ', ')"
    }
}

$psql = Find-PostgresBinary -Name "psql"
$pgIsReady = Find-PostgresBinary -Name "pg_isready"

& $pgIsReady -h $databaseHost -p $databasePort | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL is installed but its Windows service is not running on port $databasePort."
}

$adminPasswordSecure = Read-Host "Enter the PostgreSQL 'postgres' administrator password" -AsSecureString
$appPasswordSecure = Read-Host "Create a password for the Veyra database user '$databaseUser'" -AsSecureString
$appPasswordConfirmSecure = Read-Host "Enter the Veyra database password again" -AsSecureString

$adminPassword = ConvertFrom-SecureValue $adminPasswordSecure
$appPassword = ConvertFrom-SecureValue $appPasswordSecure
$appPasswordConfirm = ConvertFrom-SecureValue $appPasswordConfirmSecure

if ([string]::IsNullOrWhiteSpace($adminPassword)) {
    throw "The PostgreSQL administrator password cannot be empty."
}
if ([string]::IsNullOrWhiteSpace($appPassword)) {
    throw "The Veyra database password cannot be empty."
}
if ($appPassword -ne $appPasswordConfirm) {
    throw "The two Veyra database passwords do not match."
}

New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

$hadEnv = Test-Path -LiteralPath $backendEnv
if ($hadEnv) {
    Copy-Item -LiteralPath $backendEnv -Destination (Join-Path $backupRoot ".env.before-postgres") -Force
}
Copy-Item -LiteralPath $sqliteDb -Destination (Join-Path $backupRoot "db.sqlite3") -Force

try {
    Write-Host ""
    Write-Host "1/7 Exporting current SQLite data..." -ForegroundColor Cyan

    if (-not $hadEnv) {
        New-Item -ItemType File -Path $backendEnv -Force | Out-Null
    }

    Remove-EnvValue -Path $backendEnv -Name "DATABASE_URL"

    Push-Location $backendRoot
    try {
        & $python manage.py dumpdata `
            accounts wallets jobs blockchain workers common `
            --natural-foreign `
            --natural-primary `
            --indent 2 `
            --output $dumpFile

        if ($LASTEXITCODE -ne 0) {
            throw "Django data export failed."
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "SQLite backup created at: $backupRoot" -ForegroundColor Green

    Write-Host ""
    Write-Host "2/7 Creating PostgreSQL user and database..." -ForegroundColor Cyan

    $escapedAppPasswordSql = $appPassword.Replace("'", "''")

    $previousPgPassword = $env:PGPASSWORD
    $env:PGPASSWORD = $adminPassword
    try {
        $roleExists = & $psql `
            -h $databaseHost `
            -p $databasePort `
            -U postgres `
            -d postgres `
            -tAc "SELECT 1 FROM pg_roles WHERE rolname='$databaseUser';"

        if ($LASTEXITCODE -ne 0) {
            throw "Could not authenticate to PostgreSQL with the postgres administrator password."
        }

        $roleExistsText = ""
        if ($null -ne $roleExists) {
            $roleExistsText = [string]$roleExists
        }

        if ($roleExistsText.Trim() -eq "1") {
            & $psql `
                -h $databaseHost `
                -p $databasePort `
                -U postgres `
                -d postgres `
                -v ON_ERROR_STOP=1 `
                -c "ALTER ROLE $databaseUser WITH LOGIN PASSWORD '$escapedAppPasswordSql';"
        }
        else {
            & $psql `
                -h $databaseHost `
                -p $databasePort `
                -U postgres `
                -d postgres `
                -v ON_ERROR_STOP=1 `
                -c "CREATE ROLE $databaseUser LOGIN PASSWORD '$escapedAppPasswordSql';"
        }

        if ($LASTEXITCODE -ne 0) {
            throw "Could not create or update the Veyra PostgreSQL user."
        }

        & $psql `
            -h $databaseHost `
            -p $databasePort `
            -U postgres `
            -d postgres `
            -v ON_ERROR_STOP=1 `
            -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$databaseName' AND pid <> pg_backend_pid();"

        & $psql `
            -h $databaseHost `
            -p $databasePort `
            -U postgres `
            -d postgres `
            -v ON_ERROR_STOP=1 `
            -c "DROP DATABASE IF EXISTS $databaseName;"

        if ($LASTEXITCODE -ne 0) {
            throw "Could not reset the Veyra PostgreSQL database."
        }

        & $psql `
            -h $databaseHost `
            -p $databasePort `
            -U postgres `
            -d postgres `
            -v ON_ERROR_STOP=1 `
            -c "CREATE DATABASE $databaseName OWNER $databaseUser;"

        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the Veyra PostgreSQL database."
        }
    }
    finally {
        if ($null -eq $previousPgPassword) {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
        else {
            $env:PGPASSWORD = $previousPgPassword
        }
    }

    $encodedPassword = [Uri]::EscapeDataString($appPassword)
    $databaseUrl = "postgresql://$databaseUser`:$encodedPassword@$databaseHost`:$databasePort/$databaseName"
    Set-EnvValue -Path $backendEnv -Name "DATABASE_URL" -Value $databaseUrl

    Write-Host ""
    Write-Host "3/7 Ensuring the PostgreSQL Python driver is installed..." -ForegroundColor Cyan

    Push-Location $backendRoot
    try {
        & $python -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            throw "Python dependencies failed to install."
        }

        Write-Host ""
        Write-Host "4/7 Applying Django migrations..." -ForegroundColor Cyan

        & $python manage.py migrate
        if ($LASTEXITCODE -ne 0) {
            throw "Django migrations failed."
        }

        Write-Host ""
        Write-Host "5/7 Importing existing Veyra data..." -ForegroundColor Cyan

        & $python manage.py loaddata $dumpFile
        if ($LASTEXITCODE -ne 0) {
            throw "Veyra data import failed."
        }

        Write-Host ""
        Write-Host "6/7 Running Django checks..." -ForegroundColor Cyan

        & $python manage.py check
        if ($LASTEXITCODE -ne 0) {
            throw "Django system check failed."
        }

        Write-Host ""
        Write-Host "7/7 Confirming PostgreSQL connection..." -ForegroundColor Cyan

        & $python manage.py shell -c "from django.db import connection; assert connection.vendor == 'postgresql', connection.vendor; print('Database vendor:', connection.vendor); print('Database:', connection.settings_dict['NAME']); print('Host:', connection.settings_dict['HOST']); print('Port:', connection.settings_dict['PORT'])"
        if ($LASTEXITCODE -ne 0) {
            throw "PostgreSQL verification failed."
        }
    }
    finally {
        Pop-Location
    }

    $result = @(
        "Migration completed: $(Get-Date -Format o)",
        "SQLite backup: $(Join-Path $backupRoot 'db.sqlite3')",
        "SQLite data export: $dumpFile",
        "Previous environment: $(Join-Path $backupRoot '.env.before-postgres')",
        "PostgreSQL database: $databaseName",
        "PostgreSQL user: $databaseUser",
        "PostgreSQL host: $databaseHost",
        "PostgreSQL port: $databasePort"
    )
    [IO.File]::WriteAllLines(
        (Join-Path $backupRoot "MIGRATION-RESULT.txt"),
        [string[]]$result,
        [Text.UTF8Encoding]::new($false)
    )

    Write-Host ""
    Write-Host "VEYRA IS NOW USING NATIVE POSTGRESQL." -ForegroundColor Green
    Write-Host "PostgreSQL runs quietly as a Windows service." -ForegroundColor Green
    Write-Host "Backup kept at: $backupRoot" -ForegroundColor Yellow
}
catch {
    Write-Host ""
    Write-Host "Migration failed. Restoring the previous backend environment..." -ForegroundColor Red

    if ($hadEnv -and (Test-Path -LiteralPath (Join-Path $backupRoot ".env.before-postgres"))) {
        Copy-Item -LiteralPath (Join-Path $backupRoot ".env.before-postgres") -Destination $backendEnv -Force
    }
    elseif (-not $hadEnv -and (Test-Path -LiteralPath $backendEnv)) {
        Remove-Item -LiteralPath $backendEnv -Force
    }

    Write-Host "SQLite was not deleted. Backup: $backupRoot" -ForegroundColor Yellow
    throw
}
finally {
    $adminPassword = $null
    $appPassword = $null
    $appPasswordConfirm = $null
}
