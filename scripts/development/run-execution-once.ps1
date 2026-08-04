$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "backend"
if (-not (Test-Path -LiteralPath $python)) { throw "Veyra Python was not found: $python" }
Set-Location $backend
& $python manage.py run_execution_layer --once
