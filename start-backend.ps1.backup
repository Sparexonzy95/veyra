Set-Location "$PSScriptRoot\backend"
if (-not (Test-Path ".venv")) { py -m venv .venv }
& ".\.venv\Scripts\Activate.ps1"
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver localhost:8000
