# Worker onboarding — Phase 1 foundation

This slice adds the internal Veyra worker profile. It does not create a Circle
wallet, connect GitHub, or activate job discovery yet.

## Security boundary

The database stores only public worker configuration and readiness state. It has
no fields for:

- Circle API keys
- Circle entity secrets
- GitHub tokens
- coding-engine API keys
- private keys or recovery files

## Bootstrap the first worker

```powershell
python manage.py migrate
python manage.py bootstrap_worker
```

The command is idempotent. Running it again updates the same
`veyra-code-agent` profile instead of creating a duplicate.

## API

Staff users and users with the `ADMIN` capability may manage profiles at:

```text
GET/POST /api/v1/worker/onboarding/agents/
GET/PATCH /api/v1/worker/onboarding/agents/{id}/
```

A new profile starts in `PROFILE_READY`. It cannot become `ACTIVE` until the
engine, wallet, payout wallet, GitHub connection, contract authorisation, and
test assignment are all complete.