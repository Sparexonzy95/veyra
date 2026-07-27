$ErrorActionPreference = "Stop"
$root = "C:\Users\cashkink\Downloads\Veyra-backend\veyra-verifier-test-server"
$example = Join-Path $root ".env.example"
$target = Join-Path $root ".env"
if (-not (Test-Path -LiteralPath $example)) {
    throw "Verifier .env.example was not found: $example"
}
if (-not (Test-Path -LiteralPath $target)) {
    Copy-Item -LiteralPath $example -Destination $target
    Write-Host "Created: $target" -ForegroundColor Green
} else {
    Write-Host "Existing verifier .env preserved: $target" -ForegroundColor Yellow
}
Write-Host "Open this file and replace PASTE_SEPARATE_VERIFIER_PAID_KEY_HERE." -ForegroundColor Cyan
Write-Host "Never paste that key into ChatGPT, Django, or the frontend." -ForegroundColor Yellow
