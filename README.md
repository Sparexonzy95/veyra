# Veyra Client Actor — Django + React

This workspace contains the complete client-actor vertical slice.

```text
frontend/  React + Next.js interface using the GrantFox visual system
backend/   Django REST Framework API and Arc/Circle integration
```

GrantFox is used only as a visual reference. Veyra does not use GrantFox's Supabase, Prisma, Stellar, payout, or authentication logic.

## 1. Backend

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python manage.py check
python manage.py migrate
python manage.py runserver localhost:8000
```

Use the Circle API key and App ID already configured in your working Django `.env`. Do not copy that secret file into Git.

## 2. Arc indexer

Open another PowerShell window:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python manage.py index_arc_events --watch --interval 5
```

## 3. Frontend

```powershell
cd frontend
Copy-Item .env.example .env.local
notepad .env.local
npm install
npm run dev
```

Frontend `.env.local`:

```ini
NEXT_PUBLIC_VEYRA_API_URL=http://localhost:8000
NEXT_PUBLIC_CIRCLE_APP_ID=your_circle_app_id
NEXT_PUBLIC_GOOGLE_CLIENT_ID=your_google_web_client_id
NEXT_PUBLIC_ARC_EXPLORER_URL=https://testnet.arcscan.app
```

Open `http://localhost:3000/login`.

## Keep hosts consistent

Use:

```text
Frontend: http://localhost:3000
Backend:  http://localhost:8000
```

Do not mix `localhost` and `127.0.0.1`; the Veyra application session is an HTTP-only browser cookie.

## Test flow

```text
Google or Email login
→ Post Jobs
→ Circle Arc SCA wallet
→ Dashboard
→ Create Job
→ Review
→ USDC approval
→ Fund escrow
→ Arc JobCreated confirmation
→ Open job
```

See `frontend/docs/END_TO_END_TEST.md` for the full checklist.
