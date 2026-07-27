$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env. Add the owner-paid AI_API_KEY, then run this script again." -ForegroundColor Yellow
    notepad ".env"
    exit 1
}

$python = "C:\Users\cashkink\Downloads\Veyra-backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python server.py
