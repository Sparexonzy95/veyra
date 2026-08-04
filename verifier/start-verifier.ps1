$ErrorActionPreference = "Stop"

$verifierRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $verifierRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtime = Join-Path $projectRoot "agent-starter\server.py"
$envFile = Join-Path $verifierRoot ".env"
$stateDir = Join-Path $verifierRoot ".veyra-runtime"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Veyra Python was not found: $python"
}
if (-not (Test-Path -LiteralPath $runtime)) {
    throw "Shared Veyra runtime was not found: $runtime"
}
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Create $envFile from .env.example and add the verifier AI_API_KEY."
}

$env:VEYRA_RUNTIME_ROLE = "VERIFIER"
$env:VEYRA_RUNTIME_ENV_FILE = $envFile
$env:VEYRA_RUNTIME_STATE_DIR = $stateDir
$env:RUNTIME_BIND_HOST = "127.0.0.1"
$env:RUNTIME_PORT = "9200"
$env:RUNTIME_PUBLIC_HOST = "localhost"
$env:RUNTIME_PUBLIC_PORT = "9200"

& $python $runtime
