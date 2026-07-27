# GrantFox Frontend Handoff

GrantFox is a visual reference only. The frontend must call the Django API at `NEXT_PUBLIC_VEYRA_API_URL` and must not use GrantFox Supabase or Next.js API routes for Veyra logic.

## Browser responsibilities

- Initialize the Circle Web SDK.
- Complete Google login or email OTP.
- Keep `userToken` and `encryptionKey` in memory or session storage.
- Send `userToken` only in `X-Circle-User-Token` for wallet operations.
- Execute every returned `challenge_id` with Circle Web SDK.
- Send the Circle transaction ID back to Django after challenge completion.
- Use `credentials: "include"` for the Veyra HTTP-only session cookie.

## Backend base flow

```text
POST /api/v1/auth/circle/exchange/
POST /api/v1/onboarding/client/
POST /api/v1/client/wallet/initialize/
Circle SDK executes wallet challenge
POST /api/v1/client/wallet/sync/
GET  /api/v1/client/dashboard/
```

## Create and fund

```text
POST /api/v1/client/github/issue-preview/
POST /api/v1/client/job-drafts/
POST /api/v1/client/job-drafts/{id}/review/
POST /api/v1/client/job-drafts/{id}/approval-challenge/
Circle SDK executes approval challenge
POST /api/v1/client/job-drafts/{id}/funding-challenge/
Circle SDK executes funding challenge
POST /api/v1/client/transactions/{local_id}/
```

The job should display **Open** only when the dashboard/jobs API includes the Arc-indexed job.
