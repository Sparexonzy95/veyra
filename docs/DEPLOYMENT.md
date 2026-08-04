# Deployment

## Target layout

- Deploy `frontend/` to Vercel.
- Deploy `backend/`, `verifier/`, and one demo instance of `agent-starter/` to
  the VPS.
- External agent owners deploy their own copies of `agent-starter/`.

## Frontend (Vercel)

Set the Vercel project root to `frontend` and use the locked Next.js build.
Configure `NEXT_PUBLIC_VEYRA_API_URL`, `NEXT_PUBLIC_CIRCLE_APP_ID`,
`NEXT_PUBLIC_GOOGLE_CLIENT_ID`, and the Arc explorer base URL. The backend must
allow the final HTTPS frontend origin for CORS/CSRF and cookie policy.

## Backend (VPS)

Use Python 3.12, PostgreSQL, and a production WSGI process such as the Gunicorn
command in `backend/Dockerfile`. Copy `.env.example` to a host-managed secret
file and replace every development value. Run `manage.py migrate` before the
web process and run exactly one active execution controller for a database
lease domain.

Production values must include secure Django/cookie settings, public frontend
and API origins, PostgreSQL, Circle, GitHub App, Arc RPC, contract-authority,
and verifier settings. Put TLS at the reverse proxy; do not expose PostgreSQL or
runtime dashboards publicly.

## Demo agent and verifier (VPS)

Run the demo Agent Starter and verifier as separate service users/processes,
with separate `.env` files, identities, provider keys, temporary workspace
roots, and log streams. Only the authenticated runtime endpoints needed by the
control plane should be reachable. The verifier should remain isolated even
when both processes share a demonstration VPS.

See `../deploy/vps/README.md` for a process checklist. No host name or public
deployment URL is assumed by this repository.
