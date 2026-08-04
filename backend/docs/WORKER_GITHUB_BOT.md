# Veyra Worker GitHub Bot — Phase 1 Step 4

This step connects a dedicated GitHub account to the Veyra Code Agent.

## Security model

- The GitHub token stays in the backend runtime environment.
- The token is never stored in `WorkerAgent`.
- The command verifies `/user` and refuses a token that belongs to a different account.
- The MVP uses a dedicated bot account with access only to public repositories.
- A GitHub App should replace the personal access token before production.

## Environment variables

Add these only to the real backend `.env`:

```ini
GITHUB_BOT_USERNAME=veyra-worker-bot
GITHUB_BOT_TOKEN=replace-with-the-bot-token
GITHUB_BOT_TIMEOUT_SECONDS=20
```

Do not commit `.env`.

## Commands

Assign the existing operational wallet as the temporary payout wallet:

```powershell
python manage.py assign_worker_payout_wallet
```

Verify and connect the GitHub bot:

```powershell
python manage.py connect_worker_github
```

## Expected status

```text
PAYOUT_READY
GITHUB_READY
```

The next phase authorizes the worker wallet against the Veyra escrow contract,
then runs the test assignment.
