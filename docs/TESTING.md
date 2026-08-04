# Testing

## Python setup

From the repository root, create `.venv` and install both requirement sets:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m pip install -r agent-starter\requirements.txt
```

## Backend suite and Django checks

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py test --settings=config.test_settings --noinput
..\.venv\Scripts\python.exe manage.py check
..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

The test settings use an isolated SQLite database and mock external provider
boundaries; they should not require PostgreSQL creation privileges or live
Circle, GitHub, Arc, or model credentials.

## Agent Starter

```powershell
cd ..
.\.venv\Scripts\python.exe -m unittest discover -s agent-starter -p "test_*.py"
```

These tests cover one-time connection expiry, identity persistence/validation,
runtime retry behavior, workspace retry behavior, and model path-policy repair.

## Frontend

```powershell
cd frontend
npm.cmd install
npm.cmd run typecheck
npm.cmd run build
```

`npm.cmd run build` creates `frontend/.next`; it is generated and must not be
committed. `node_modules`, TypeScript build metadata, test caches, SQLite files,
and Python bytecode are also disposable.
