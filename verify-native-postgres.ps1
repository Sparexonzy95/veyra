$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\cashkink\Downloads\Veyra-backend"
$backendRoot = Join-Path $projectRoot "veyra-client-backend"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

Push-Location $backendRoot
try {
    & $python manage.py check
    if ($LASTEXITCODE -ne 0) {
        throw "Django check failed."
    }

    & $python manage.py shell -c "from django.db import connection; assert connection.vendor == 'postgresql', f'Expected postgresql, got {connection.vendor}'; print('PostgreSQL connection confirmed'); print('Database:', connection.settings_dict['NAME']); print('Host:', connection.settings_dict['HOST']); print('Port:', connection.settings_dict['PORT'])"
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL verification failed."
    }
}
finally {
    Pop-Location
}
