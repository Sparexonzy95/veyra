# Veyra Funding + Receipt Confirmation Flow v0.5.0

This patch removes the client funding dependency on the global Arc event indexer.

## New flow

1. Django creates and stores a Circle transaction record.
2. Circle returns a challenge ID.
3. The browser executes the challenge.
4. The browser returns the Circle transaction ID to Django.
5. Django retrieves the Circle transaction and stores the Arc transaction hash.
6. The frontend polls only that stored transaction.
7. Django retrieves the exact Arc receipt and original transaction.
8. Django validates sender, target contract and call-data hash.
9. Approval confirmation checks the actual USDC allowance.
10. Funding confirmation decodes and validates the exact JobCreated event.
11. Django creates VeyraJob, marks the draft FUNDED and returns the onchain job ID.
12. The UI shows "Job funded and open".

## Replace files

Copy every file from this patch into the matching path in your workspace.

Backend workspace:
  C:\Users\cashkink\Downloads\Veyra-backend\veyra-client-backend

Frontend workspace:
  C:\Users\cashkink\Downloads\Veyra-backend\frontend

## Run after copying

Backend:
  .\.venv\Scripts\Activate.ps1
  python manage.py migrate
  python manage.py check
  python manage.py test
  python manage.py runserver localhost:8000

Frontend:
  npm.cmd run typecheck
  npm.cmd run dev

Open:
  http://localhost:3000

## Important

Do not run index_arc_events for client approval or job funding.
The exact known transaction receipt now finalises those actions.

The indexer may remain available later for observing unrelated worker/verifier
events, but it is no longer part of this client funding path.

## Validation performed

- Django system check passed
- Django migrations are consistent
- 14 backend tests passed
- Frontend strict TypeScript check passed
- Next.js compiled and generated all static pages
