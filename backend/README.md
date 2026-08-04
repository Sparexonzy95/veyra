# Veyra backend

This directory contains the Django REST API and control plane for Veyra. It
owns application sessions, Circle wallet orchestration, exact Arc receipt
reconciliation, GitHub App access, agent eligibility and assignment, execution
leases, independent verification, and settlement orchestration.

## Development

From the repository root, create `.venv`, install `backend/requirements.txt`,
copy `backend/.env.example` to `backend/.env`, and configure local values.

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py runserver localhost:8000
```

Run checks with the isolated test settings:

```powershell
..\.venv\Scripts\python.exe manage.py test --settings=config.test_settings --noinput
..\.venv\Scripts\python.exe manage.py check
..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

The normal funding path reconciles the exact Circle transaction and Arc receipt
recorded for the job. The optional event indexer is not required to confirm
client funding. See `../docs/ARCHITECTURE.md` and `../docs/ARC_INTEGRATION.md`.
