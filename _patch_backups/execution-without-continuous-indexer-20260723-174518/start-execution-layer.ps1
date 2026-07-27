$ErrorActionPreference = "Stop"
$root = "C:\Users\cashkink\Downloads\Veyra-backend"
$python = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "veyra-client-backend"
if (-not (Test-Path -LiteralPath $python)) { throw "Veyra Python was not found: $python" }
if (-not (Test-Path -LiteralPath $backend)) { throw "Veyra backend was not found: $backend" }
Set-Location $backend
Write-Host "Starting Veyra autonomous execution control plane..." -ForegroundColor Cyan
& $python manage.py run_execution_layer --interval 5
