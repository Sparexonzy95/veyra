# Agent Runtime Pairing: Phase 1 Step 2

This phase connects an externally owned Veyra agent to an owner-hosted Veyra Runner.

## Implemented

- Owner-generated, short-lived, one-time pairing codes.
- Pairing codes stored only as keyed hashes.
- A local Runner device keypair that never leaves the owner machine.
- EIP-191 device proof during pairing.
- Signed heartbeat requests with timestamp and nonce replay protection.
- One Runner device hosting multiple Veyra agents owned by the same user.
- Dynamic runtime states: `NOT_CONNECTED`, `PAIRED`, `ONLINE`, `OFFLINE`, `UNHEALTHY`, and `REVOKED`.
- Owner-scoped runtime pairing, status, and revoke endpoints.
- Frontend runtime pairing card and live agent detail page.

## Security boundaries

The Runner device key authenticates the machine to Veyra. It is not an Arc wallet, must not receive funds, and is unrelated to Circle wallet custody.

The Runner never sends these secrets to Veyra:

- model provider API keys;
- GitHub credentials;
- Circle API keys or entity secrets;
- Arc private keys;
- repository secrets.

## Owner API

- `POST /api/v1/agents/{agent_id}/runtime/pairing-code/`
- `GET /api/v1/agents/{agent_id}/runtime/status/`
- `POST /api/v1/agents/{agent_id}/runtime/revoke/`

## Runner API

- `POST /api/v1/runner/pair/`
- `POST /api/v1/runner/heartbeat/`

## Local test flow

From the backend directory:

```powershell
python manage.py migrate
python manage.py test workers.test_runtime_pairing -v 2
```

From the frontend directory:

```powershell
npm run typecheck
```

From `veyra-runner`:

```powershell
python runner.py pair --server http://localhost:8000 --name "Maryam Development Runner"
python runner.py start --once
python runner.py status
```

After the signed heartbeat, the agent detail API and dashboard should report runtime status `ONLINE`, and onboarding should advance to the GitHub step.
