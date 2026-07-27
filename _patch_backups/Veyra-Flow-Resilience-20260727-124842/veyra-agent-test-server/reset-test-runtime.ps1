$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$state = Join-Path $root ".veyra-runtime"
if (Test-Path $state) {
    Remove-Item -LiteralPath $state -Recurse -Force
}
Write-Host "Local runtime identity and connection state reset." -ForegroundColor Green
