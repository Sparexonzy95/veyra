# React to Django API Mapping

| Frontend action | Django endpoint |
| --- | --- |
| Prepare Google login | `POST /api/v1/auth/circle/social/device/` |
| Request email OTP | `POST /api/v1/auth/circle/email/request/` |
| Exchange Circle session | `POST /api/v1/auth/circle/exchange/` |
| Restore Veyra session | `GET /api/v1/auth/me/` |
| Choose Post Jobs | `POST /api/v1/onboarding/client/` |
| Initialize Arc wallet | `POST /api/v1/client/wallet/initialize/` |
| Sync Arc wallet | `POST /api/v1/client/wallet/sync/` |
| Read wallet | `GET /api/v1/client/wallet/` |
| Refresh USDC balance | `GET /api/v1/client/wallet/balance/` |
| Dashboard | `GET /api/v1/client/dashboard/` |
| Preview GitHub issue | `POST /api/v1/client/github/issue-preview/` |
| Create draft | `POST /api/v1/client/job-drafts/` |
| Edit draft | `PATCH /api/v1/client/job-drafts/{id}/` |
| Review draft | `POST /api/v1/client/job-drafts/{id}/review/` |
| Prepare exact allowance | `POST /api/v1/client/job-drafts/{id}/approval-challenge/` |
| Prepare job funding | `POST /api/v1/client/job-drafts/{id}/funding-challenge/` |
| List client jobs | `GET /api/v1/client/jobs/` |
| Read job | `GET /api/v1/client/jobs/{onchainJobId}/` |
| Cancel or refund | `POST /api/v1/client/jobs/{onchainJobId}/action-challenge/` |
| Record Circle transaction ID | `POST /api/v1/client/transactions/{id}/` |
| Read transaction status | `GET /api/v1/client/transactions/{id}/` |
| Log out | `POST /api/v1/auth/logout/` |
