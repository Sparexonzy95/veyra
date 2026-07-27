# Veyra Client Frontend

React/Next.js client for the Veyra client actor. The visual system is adapted from the uploaded GrantFox frontend reference. GrantFox business logic, Supabase, Prisma, Stellar, and payout APIs are not used.

## Architecture

```text
React / Next.js frontend
        ↓ REST + HTTP-only cookie
Django REST Framework
        ↓
PostgreSQL
        ↓
Circle User-Controlled Wallets + Arc Testnet
```

## Visible client flow

```text
Continue with Google or Email
→ Choose Post Jobs
→ Circle prepares Arc SCA wallet
→ Dashboard
→ Create Job
→ Review Job
→ Approve and Fund
→ Open → Agent Working → Under Review → Completed / Refunded
```

## Visual source

The interface keeps the GrantFox visual language:

- white/light card surfaces;
- orange primary actions;
- the same compact sidebar shell;
- the same border radius, spacing, dialogs, tabs, cards, typography hierarchy, and form treatment;
- no gradients, glassmorphism, neon effects, AI-themed illustrations, or futuristic styling.

Only labels and data were changed to match Veyra.

## Requirements

- Node.js 20+
- npm 10+
- Django backend running on `http://localhost:8000`
- Circle User-Controlled Wallet App ID
- Google Web OAuth Client ID configured in Circle

## Configure

Copy the example file:

```powershell
Copy-Item .env.example .env.local
notepad .env.local
```

Set:

```ini
NEXT_PUBLIC_VEYRA_API_URL=http://localhost:8000
NEXT_PUBLIC_CIRCLE_APP_ID=your_circle_app_id
NEXT_PUBLIC_GOOGLE_CLIENT_ID=your_google_web_client_id
NEXT_PUBLIC_ARC_EXPLORER_URL=https://testnet.arcscan.app
```

Never place `CIRCLE_API_KEY` in this frontend.

## Install and run

```powershell
npm install
npm run dev
```

Open:

```text
http://localhost:3000/login
```

Use `localhost` consistently for both frontend and backend. Do not mix `localhost` and `127.0.0.1`, because Veyra authentication uses secure browser cookies.

## Production checks

```powershell
npm run typecheck
npm run build
npm start
```

## Django requirements

The Django `.env` must include:

```ini
CORS_ALLOWED_ORIGINS=http://localhost:3000
CIRCLE_API_KEY=your_testnet_circle_api_key
CIRCLE_APP_ID=your_circle_app_id
CIRCLE_BASE_URL=https://api.circle.com
```

Start Django:

```powershell
python manage.py runserver localhost:8000
```

Run the Arc indexer in another terminal:

```powershell
python manage.py index_arc_events --watch --interval 5
```

## Main routes

- `/login`
- `/dashboard`
- `/dashboard/jobs`
- `/dashboard/jobs/[onchainJobId]`
- `/dashboard/profile`

## Important behavior

- Circle `userToken`, `encryptionKey`, and refresh data stay in browser session storage, not local storage.
- The Django session is an HTTP-only cookie.
- Contract addresses and calldata are created by Django, never accepted from the browser.
- A job appears as Open only after the Arc `JobCreated` event is indexed.
- Cancellation and refund use one contextual UI action; Django selects the correct contract function.
