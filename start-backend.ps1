$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$backendPath = Join-Path $projectRoot "backend"
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonPath)) {
    Write-Host "Creating backend virtual environment..." -ForegroundColor Cyan
    py -m venv (Join-Path $projectRoot ".venv")
}

if (-not (Test-Path $backendPath)) {
    throw "Backend folder not found: $backendPath"
}

Set-Location $backendPath

Write-Host "Applying Django migrations..." -ForegroundColor Cyan
& $pythonPath manage.py migrate

Write-Host ""
Write-Host "Starting Veyra backend at http://localhost:8000" -ForegroundColor Green
& $pythonPath manage.py runserver localhost:8000
