$ErrorActionPreference = "Stop"
$frontendRoot = Join-Path $PSScriptRoot "frontend"
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules") -PathType Container)) {
    throw "frontend/node_modules is missing. Install dependencies before starting Veyra."
}
Set-Location $frontendRoot
& npm.cmd run dev
exit $LASTEXITCODE
