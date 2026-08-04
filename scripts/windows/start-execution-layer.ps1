$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "backend"
if (-not (Test-Path -LiteralPath $python)) { throw "Veyra Python was not found: $python" }
if (-not (Test-Path -LiteralPath $backend)) { throw "Veyra backend was not found: $backend" }
Set-Location $backend
$env:PYTHONUNBUFFERED = "1"
$logPath = Join-Path ([IO.Path]::GetTempPath()) "veyra-execution-layer.log"
$restartDelaySeconds = 10

Write-Host "Starting Veyra execution control plane with targeted transaction reconciliation..." -ForegroundColor Cyan
Write-Host "Structured cycle log: $logPath" -ForegroundColor Cyan

while ($true) {
    # Windows PowerShell 5 wraps native stderr records as NativeCommandError.
    # Django intentionally emits structured logs on stderr, so those records
    # must not terminate the watchdog; the native exit code remains authoritative.
    $ErrorActionPreference = "Continue"
    & $python manage.py run_execution_layer --interval 5 --max-interval 120 2>&1 |
        Tee-Object -FilePath $logPath -Append
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    Write-Warning "Execution layer exited with code $exitCode. Restarting in $restartDelaySeconds seconds."
    Start-Sleep -Seconds $restartDelaySeconds
}
