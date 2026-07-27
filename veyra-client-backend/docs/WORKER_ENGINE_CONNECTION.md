# Worker Onboarding — Phase 1, Step 2

This step connects the Veyra worker profile to the local OpenCode runtime while
keeping provider credentials outside Django.

## What is verified

- The worker uses the `OPENCODE` provider.
- The configured model is `zai-org/glm-5.2`.
- The OpenCode executable exists on the backend machine.
- `opencode --version` returns successfully within the timeout.
- The detected runtime version and health-check time are stored.

This is a runtime connection check, not the final coding test. The Phase 2 test
assignment will prove that the engine can edit a repository and run tests.

## Secrets

The database does not store:

- ai& API keys
- OpenCode login credentials
- Circle secrets
- GitHub tokens

OpenCode continues to use its own local/global authentication configuration.

## Environment

```ini
WORKER_ENGINE_EXECUTABLE=opencode
WORKER_ENGINE_HEALTHCHECK_ARGS=--version
WORKER_ENGINE_TIMEOUT_SECONDS=20
WORKER_ENGINE_MODEL=zai-org/glm-5.2
```

When `opencode` is not on `PATH`, set `WORKER_ENGINE_EXECUTABLE` to its full
Windows path.

## Commands

```powershell
python manage.py migrate
python manage.py check
python manage.py test
python manage.py connect_worker_engine
```

Expected result:

```text
Connected coding engine: OPENCODE
Worker: Veyra Code Agent
Status: ENGINE_CONNECTED
Model: zai-org/glm-5.2
Runtime version: ...
Secrets stored in database: none
```

## Admin API

```text
POST /api/v1/worker/onboarding/agents/{worker_id}/connect-engine/
```

Only a Veyra administrator may call this endpoint.