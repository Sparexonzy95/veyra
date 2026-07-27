$ErrorActionPreference = "Stop"
$root = "C:\Users\cashkink\Downloads\Veyra-backend"
$python = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "veyra-client-backend"
if (-not (Test-Path -LiteralPath $python)) { throw "Veyra Python was not found: $python" }
Set-Location $backend
& $python manage.py run_execution_layer --once
