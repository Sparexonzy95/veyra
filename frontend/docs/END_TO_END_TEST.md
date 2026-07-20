# Client Actor End-to-End Test

## Terminals

### Terminal 1 — Django

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python manage.py check
python manage.py migrate
python manage.py runserver localhost:8000
```

### Terminal 2 — Arc indexer

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python manage.py index_arc_events --watch --interval 5
```

### Terminal 3 — React frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000/login`.

## Test sequence

1. Click **Continue with Google**.
2. Complete Google authentication through Circle.
3. Choose **Post Jobs**.
4. Approve the Circle Arc wallet setup challenge.
5. Confirm the dashboard displays the Arc wallet address.
6. Fund the wallet with Arc Testnet USDC when its balance is insufficient.
7. Click **Create Job**.
8. Paste a public GitHub issue URL.
9. Confirm Veyra loads the repository and issue.
10. Enter budget, deadline, and acceptance criteria.
11. Review the job.
12. Click **Fund Job**.
13. Approve the exact USDC allowance challenge when requested.
14. Approve the job funding challenge.
15. Keep the indexer terminal running.
16. Confirm the job appears as **Open** after `JobCreated` is indexed.
17. Use the temporary worker/verifier harness later to move it through Agent Working, Under Review, and Completed/Refunded.

## Expected security behavior

- The Circle API key never appears in browser DevTools.
- The frontend cannot choose an arbitrary contract address or calldata.
- Closing the browser removes the Circle wallet session; the Django dashboard session may remain.
- A returning user can view jobs and is asked to reconnect Circle only before a wallet action.
- Repeated funding clicks reuse the active backend transaction intent.

## Common local errors

### Django cookie is not retained

Use `localhost` for both services:

```text
Frontend: http://localhost:3000
Backend:  http://localhost:8000
```

### CORS or origin blocked

Set Django:

```ini
CORS_ALLOWED_ORIGINS=http://localhost:3000
```

Restart Django after editing `.env`.

### Google redirect mismatch

Google Cloud and Circle must use the same Web Client ID. For local testing, the allowed origin and redirect are:

```text
http://localhost:3000
```

### Wallet challenge succeeds but wallet is not shown immediately

Circle may take a moment to expose the wallet. The frontend retries wallet sync automatically.

### Funding submitted but job is not Open

Keep the Arc indexer running. Circle submission alone is not final; the Django projection waits for the confirmed `JobCreated` event.
