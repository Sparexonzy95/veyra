# VPS deployment checklist

This directory documents the intended VPS layout; it does not contain host- or
provider-specific URLs.

## Services

Run these as independently supervised processes:

1. PostgreSQL, reachable only by the backend service account.
2. Django/Gunicorn from `backend/`, behind an HTTPS reverse proxy.
3. One `manage.py run_execution_layer` controller. Its database lease prevents
   an accidental second active controller, but supervision should still define
   a single desired instance.
4. One demo runtime from `agent-starter/`.
5. One verifier runtime using `verifier/start-verifier.ps1` on Windows or the
   equivalent environment variables and `agent-starter/server.py` invocation
   under a Linux service manager.

## Release order

1. Copy source without `.env`, identities, logs, databases, dependency trees,
   or build output.
2. Create service users, virtual environments, secret files, and temporary
   workspace directories.
3. Install locked/declared dependencies.
4. Run backend tests, `manage.py check`, and migration drift checks.
5. Back up PostgreSQL, then run `manage.py migrate`.
6. Restart the web service, execution controller, demo agent, and verifier.
7. Check `/api/health/` through the reverse proxy and inspect the authenticated
   runtime health views without exposing their dashboards publicly.

## Required separation

The demo agent and verifier need different `.env` files, provider API keys,
runtime state directories, ports, and service users. Store the contract signer
outside source control and restrict it to the backend process. External agent
owners receive only `agent-starter`; they do not receive backend, verifier, or
settlement secrets.
